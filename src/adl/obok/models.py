"""Domain models for Kobo DRM interaction."""

from __future__ import annotations

import base64
import binascii
import hashlib
import logging
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import zipfile
from typing import Optional

from xml.etree import ElementTree as ET

from Cryptodome.Cipher import AES

from adl.obok.crypto import unpad

logger = logging.getLogger(__name__)

# Known hash keys for deriving user encryption keys
KOBO_HASH_KEYS = ["88b3a2e13", "XzUhGYdFp", "NoCanLook", "QJhwzAtXL"]


def _is_windows() -> bool:
    return sys.platform.startswith("win")


def _is_darwin() -> bool:
    return sys.platform.startswith("darwin")


def _is_linux() -> bool:
    return sys.platform.startswith("linux")


class ENCRYPTIONError(Exception):
    """Raised when decryption fails."""


class KoboFile:
    """An encrypted file inside a Kobo book.

    Each file has:
        filename: relative path inside the book zip
        mimetype: MIME type (e.g. 'image/jpeg')
        key: encrypted page key
    """

    def __init__(self, filename: str, mimetype: Optional[str], key: bytes) -> None:
        self.filename = filename
        self.mimetype = mimetype
        self.key = key

    def decrypt(self, userkey: bytes, contents: bytes) -> bytes:
        """Decrypt content using the provided user key and this file's page key."""
        decrypted_key = AES.new(userkey, AES.MODE_ECB).decrypt(self.key)
        return unpad(AES.new(decrypted_key, AES.MODE_ECB).decrypt(contents), 16)

    def check(self, contents: bytes) -> bool:
        """Validate that decrypted content matches its expected MIME type.

        Raises ValueError if the content does not match expectations.
        Returns True if checked successfully, False if unchecked type.
        """
        if self.mimetype == "application/xhtml+xml":
            return self._check_xml(contents)
        elif self.mimetype == "image/jpeg":
            if contents[:3] == b"\xff\xd8\xff":
                return True
            logger.error("Bad JPEG: %s", contents[:3].hex())
            raise ValueError("Decrypted content is not a valid JPEG")

        return False

    def _check_xml(self, contents: bytes) -> bool:
        """Validate XML content encoding and structure."""
        textoffset = 0
        stride = 1

        # Detect BOM / encoding
        if contents[:3] == b"\xef\xbb\xbf":
            logger.debug("Detected UTF-8 with BOM")
            textoffset = 3
        elif contents[:2] == b"\xfe\xff":
            logger.debug("Detected UTF-16BE")
            textoffset = 3
            stride = 2
        elif contents[:2] == b"\xff\xfe":
            logger.debug("Detected UTF-16LE")
            textoffset = 2
            stride = 2
        else:
            logger.debug("Assuming UTF-8 without BOM")

        # Check first few characters are ASCII-range printable
        for i in range(textoffset, min(textoffset + 5 * stride, len(contents)), stride):
            byte = contents[i]
            if byte < 32 or byte > 127:
                logger.error("Non-ASCII byte at offset %d (value %d)", i, byte)
                raise ValueError(
                    "Decrypted XML contains non-ASCII bytes where expected"
                )

        # Check for valid XML start markers
        xml_starts = [
            b"<?xml",
            b"\xef\xbb\xbf<?xml",
            b"<!DOCTYPE",
            b"\xef\xbb\xbf<!DOCTYPE",
        ]
        utf16be_starts = [
            b"\xfe\xff\x00<\x00?\x00x\x00m\x00l",
            b"\xfe\xff\x00<\x00!\x00D\x00O\x00C\x00T\x00Y\x00P\x00E",
        ]
        utf16le_starts = [
            b"\xff\xfe<\x00?\x00x\x00m\x00l\x00",
            b"\xff\xfe<\x00!\x00D\x00O\x00C\x00T\x00Y\x00P\x00E\x00",
        ]

        if any(contents.startswith(marker) for marker in xml_starts):
            return True
        if any(contents.startswith(marker) for marker in utf16be_starts):
            return True
        if any(contents.startswith(marker) for marker in utf16le_starts):
            return True

        logger.error("Bad XML start: %r", contents[:8])
        raise ValueError("Decrypted content does not look like valid XML")


# Regex pattern for sanitizing filenames (precompiled to avoid f-string escape issues on 3.9)
_SANITIZE_FILENAME_RE = re.compile(r"[^\s\w]")


class KoboBook:
    """Represents a single book from the Kobo library.

    Attributes:
        volumeid: UUID identifying the book
        title: Human-readable book title
        filename: Full path to the book file on disk
        type: 'kepub' or 'drm-free'
        author: Author name (optional)
        series: Series info (optional)
    """

    def __init__(
        self,
        volumeid: str,
        title: str,
        filename: str,
        book_type: str,
        cursor: sqlite3.Cursor,
        author: Optional[str] = None,
        series: Optional[str] = None,
    ) -> None:
        self.volumeid = volumeid
        self.title = title
        self.author = author
        self.series = series
        self.series_index: Optional[float] = None
        self.filename = filename
        self.type = book_type
        self._cursor = cursor
        self._encrypted_files: dict[str, KoboFile] | None = None

    @property
    def encryptedfiles(self) -> dict[str, KoboFile]:
        """Dictionary of encrypted files keyed by relative path."""
        if self.type == "drm-free":
            return {}
        if self._encrypted_files is not None:
            return self._encrypted_files

        self._encrypted_files = {}

        # Fetch encrypted file entries from the database
        for row in self._cursor.execute(
            "SELECT elementid, elementkey FROM content_keys, content "
            "WHERE volumeid = ? AND volumeid = contentid",
            (self.volumeid,),
        ):
            self._encrypted_files[row[0]] = KoboFile(
                row[0], None, base64.b64decode(row[1])
            )

        # Read the OPF manifest to populate MIME types
        zin = zipfile.ZipFile(self.filename, "r")
        xmlns = {
            "ocf": "urn:oasis:names:tc:opendocument:xmlns:container",
            "opf": "http://www.idpf.org/2007/opf",
        }

        ocf = ET.fromstring(zin.read("META-INF/container.xml"))
        opffile = ocf.find(".//ocf:rootfile", xmlns).attrib["full-path"]
        basedir = re.sub(r"[^/]+$", "", opffile)
        opf = ET.fromstring(zin.read(opffile))
        zin.close()

        slash_re = re.compile(r"/")
        for item in opf.findall(".//opf:item", xmlns):
            mimetype = item.attrib["media-type"]
            href = item.attrib["href"]
            if not slash_re.match(href):
                href = basedir + href

            if href in self._encrypted_files:
                self._encrypted_files[href].mimetype = mimetype

        return self._encrypted_files

    @property
    def has_drm(self) -> bool:
        """Whether this book is DRM-protected."""
        return self.type != "drm-free"


class KoboLibrary:
    """Interface to a Kobo library (desktop app or device).

    Provides access to user encryption keys and the list of books.
    """

    def __init__(
        self,
        serials: list[str] | None = None,
        device_path: Optional[str] = None,
        desktop_kobodir: str = "",
    ) -> None:
        from adl.obok import __about__

        print(__about__)
        self._serials: list[str] = serials or []
        self.kobodir: str = ""
        self.bookdir: str = ""
        self._sqlite: sqlite3.Connection | None = None
        self._cursor: sqlite3.Cursor | None = None
        self._newdb_path: str = ""
        self._userkeys: list[bytes] | None = None
        self._books: list[KoboBook] | None = None
        self._volume_ids: list[str] = []

        # Locate the Kobo data directory and database
        db_path = self._locate_database(device_path, desktop_kobodir)

        if db_path:
            self._open_database(db_path)

    def _locate_database(
        self, device_path: Optional[str], desktop_kobodir: str
    ) -> Optional[str]:
        """Find the Kobo SQLite database path."""
        # Step 1: Check for a device path
        if device_path:
            kobodir = os.path.join(device_path, ".kobo")
            db_path = os.path.join(kobodir, "KoboReader.sqlite")
            if os.path.isfile(db_path):
                self.kobodir = kobodir

                # Step 3: Try to extract serial from device XML
                if len(self._serials) == 0:
                    devicexml = os.path.join(
                        device_path, ".adobe-digital-editions", "device.xml"
                    )
                    if os.path.exists(devicexml):
                        try:
                            tree = ET.parse(devicexml)
                            for node in tree.iter():
                                if "deviceSerial" in node.tag:
                                    self._serials.append(node.text)
                                    break
                        except Exception as e:
                            logger.warning("Failed to parse device.xml: %s", e)

                return db_path

        # Step 4: Fall back to desktop app locations
        if desktop_kobodir:
            self.kobodir = desktop_kobodir
        else:
            self.kobodir = self._find_desktop_directory()

        if not self.kobodir:
            return None

        db_path = os.path.join(self.kobodir, "Kobo.sqlite")
        if os.path.isfile(db_path):
            return db_path

        return None

    def _find_desktop_directory(self) -> str:
        """Determine the Kobo Desktop Edition directory for this platform."""
        if _is_windows():
            return self._find_windows_kobodir()
        elif _is_darwin():
            return os.path.join(
                os.environ["HOME"],
                "Library",
                "Application Support",
                "Kobo",
                "Kobo Desktop Edition",
            )
        elif _is_linux():
            return self._find_linux_kobodir()

        return ""

    def _find_windows_kobodir(self) -> str:
        """Locate Kobo directory on Windows via registry and environment."""
        try:
            import winreg
        except ImportError:
            import _winreg as winreg  # type: ignore[no-redef]

        kobodir = ""
        if sys.getwindowsversion().major > 5:
            if "LOCALAPPDATA" in os.environ:
                kobodir = winreg.ExpandEnvironmentStrings("%LOCALAPPDATA%")

        if not kobodir and "USERPROFILE" in os.environ:
            kobodir = os.path.join(
                winreg.ExpandEnvironmentStrings("%USERPROFILE%"),
                "Local Settings",
                "Application Data",
            )

        return os.path.join(kobodir, "Kobo", "Kobo Desktop Edition") if kobodir else ""

    def _find_linux_kobodir(self) -> str:
        """Locate Kobo directory on Linux with caching."""
        cache_dir = os.path.join(os.environ["HOME"], ".config", "calibre")
        if not os.path.isdir(cache_dir):
            os.mkdir(cache_dir)

        cache_file = os.path.join(cache_dir, "kobo location")

        if not os.path.isfile(cache_file):
            for root, _dirs, files in os.walk("/"):
                if "Kobo.sqlite" in files:
                    with open(cache_file, "w") as f:
                        f.write(root)
                    break

        try:
            with open(cache_file, "r") as f:
                return f.read().strip()
        except OSError:
            return ""

    def _open_database(self, db_path: str) -> None:
        """Copy the database to a temp file and connect."""
        self.bookdir = os.path.join(self.kobodir, "kepub")

        # Copy DB to ensure WAL mode doesn't interfere with sqlite3 module
        self._newdb_path = tempfile.mktemp(suffix=".sqlite")
        olddb = open(db_path, "rb")
        with open(self._newdb_path, "wb") as newdb:
            newdb.write(olddb.read(18))
            newdb.write(b"\x01\x01")
            olddb.read(2)
            newdb.write(olddb.read())

        olddb.close()

        self._sqlite = sqlite3.connect(self._newdb_path)
        self._sqlite.text_factory = lambda b: b.decode("utf-8", errors="ignore")
        self._cursor = self._sqlite.cursor()

    def close(self) -> None:
        """Close the database and clean up temp files."""
        if self._cursor:
            self._cursor.close()
        if self._sqlite:
            self._sqlite.close()
        if self._newdb_path and os.path.exists(self._newdb_path):
            try:
                os.remove(self._newdb_path)
            except OSError:
                pass

    @property
    def userkeys(self) -> list[bytes]:
        """List of potential user encryption keys (only one will be valid)."""
        if self._userkeys is None:
            self._userkeys = []
            for mac_addr in self._get_mac_addresses():
                self._userkeys.extend(self._get_user_keys(mac_addr))
        return self._userkeys

    @property
    def books(self) -> list[KoboBook]:
        """List of KoboBook instances in the library."""
        if self._books is None:
            assert self._cursor is not None, "Database not opened"
            self._books = []

            cursor = self._cursor

            # DRM-protected kepub books from database
            for row in cursor.execute(
                "SELECT DISTINCT volumeid, Title, Attribution, Series "
                "FROM content_keys, content WHERE contentid = volumeid"
            ):
                book_dir = os.path.join(self.kobodir, "kepub", row[0])
                self._books.append(
                    KoboBook(
                        row[0],
                        row[1],
                        book_dir,
                        "kepub",
                        cursor,
                        author=row[2],
                        series=row[3],
                    )
                )
                self._volume_ids.append(row[0])

            # DRM-free books found on disk
            if os.path.isdir(self.bookdir):
                for entry in os.listdir(self.bookdir):
                    if entry not in self._volume_ids:
                        row = cursor.execute(
                            "SELECT Title, Attribution, Series FROM content "
                            "WHERE ContentID = '" + entry + "'"
                        ).fetchone()
                        if row is not None:
                            book_path = os.path.join(self.bookdir, entry)
                            self._books.append(
                                KoboBook(
                                    entry,
                                    row[0],
                                    book_path,
                                    "drm-free",
                                    cursor,
                                    author=row[1],
                                    series=row[2],
                                )
                            )
                            self._volume_ids.append(entry)

            self._books.sort(key=lambda b: b.title)

        return self._books

    def _get_mac_addresses(self) -> list[str]:
        """Collect all MAC addresses on the machine plus stored serials."""
        mac_addrs: list[str] = []

        if _is_windows():
            mac_addrs.extend(self._get_windows_macs())
        elif _is_darwin():
            mac_addrs.extend(self._get_darwin_macs())
        elif _is_linux():
            mac_addrs.extend(self._get_linux_macs())
        else:
            mac_addrs.extend(self._get_fallback_macs())

        # Serials also serve as valid identifiers
        mac_addrs.extend(self._serials)
        return mac_addrs

    def _get_windows_macs(self) -> list[str]:
        """Extract MAC addresses on Windows via ipconfig/wmic."""
        mac_re = re.compile(
            r"\s?(" + r"[0-9a-f]{2}[:\-]" * 5 + r"[0-9a-f]{2})(\s|$)", re.IGNORECASE
        )
        macs: list[str] = []

        try:
            proc = subprocess.Popen(
                "ipconfig /all", shell=True, stdout=subprocess.PIPE, text=True
            )
            for line in proc.stdout or []:
                m = mac_re.search(line)
                if m:
                    macs.append(re.sub("-", ":", m.group(1)).upper())
        except Exception:
            pass

        # Fallback to wmic if ipconfig yielded nothing
        if not macs:
            try:
                proc = subprocess.Popen(
                    "wmic nic where PhysicalAdapter=True get MACAddress",
                    shell=True,
                    stdout=subprocess.PIPE,
                    text=True,
                )
                for line in proc.stdout or []:
                    m = mac_re.search(line)
                    if m:
                        macs.append(re.sub("-", ":", m.group(1)).upper())
            except Exception:
                pass

        return macs

    def _get_darwin_macs(self) -> list[str]:
        """Extract MAC addresses on macOS via ifconfig."""
        mac_re = re.compile(
            r"\s(" + r"[0-9a-f]{2}:" * 5 + r"[0-9a-f]{2})(\s|$)", re.IGNORECASE
        )
        try:
            output = subprocess.check_output(
                "/sbin/ifconfig -a", shell=True, encoding="utf-8"
            )
            return [m[0].upper() for m in mac_re.findall(output)]
        except Exception:
            return []

    def _get_linux_macs(self) -> list[str]:
        """Extract MAC addresses on Linux via /sys/class/net."""
        macs: list[str] = []
        net_dir = "/sys/class/net"
        if os.path.isdir(net_dir):
            for iface in os.listdir(net_dir):
                addr_file = os.path.join(net_dir, iface, "address")
                try:
                    with open(addr_file, "r") as f:
                        mac = f.read().strip().upper()
                        if mac:
                            macs.append(mac)
                except OSError:
                    pass
        return macs

    def _get_fallback_macs(self) -> list[str]:
        """Fallback MAC detection via ip / ipconfig commands."""
        macs: list[str] = []
        mac_re_colon = re.compile(
            r"\s(" + r"[0-9a-f]{2}:" * 5 + r"[0-9a-f]{2})(\s|$)", re.IGNORECASE
        )
        mac_re_dash = re.compile(
            r"\s(" + r"[0-9a-f]{2}-" * 5 + r"[0-9a-f]{2})(\s|$)", re.IGNORECASE
        )

        try:
            for line in os.popen("ip -br link"):
                m = mac_re_colon.search(line)
                if m:
                    macs.append(m.group(1).upper())
        except Exception:
            pass

        try:
            for line in os.popen("ipconfig /all"):
                m = mac_re_dash.search(line)
                if m:
                    macs.append(re.sub("-", ":", m.group(1)).upper())
        except Exception:
            pass

        return macs

    def _get_user_ids(self) -> list[str]:
        """Extract user IDs from the Kobo database."""
        if self._cursor is None:
            return []
        userids: list[str] = []
        cursor = self._cursor.execute("SELECT UserID FROM user")
        row = cursor.fetchone()
        while row is not None:
            try:
                userids.append(row[0])
            except Exception:
                pass
            row = cursor.fetchone()
        return userids

    def _get_user_keys(self, mac_addr: str) -> list[bytes]:
        """Derive potential user encryption keys from a MAC address."""
        userids = self._get_user_ids()
        userkeys: list[bytes] = []

        for hash_key in KOBO_HASH_KEYS:
            device_id = hashlib.sha256(
                (hash_key + mac_addr).encode("ascii")
            ).hexdigest()
            for userid in userids:
                userkey_full = hashlib.sha256(
                    (device_id + userid).encode("ascii")
                ).hexdigest()
                # Use the second half of the hash as the actual key bytes
                userkeys.append(binascii.a2b_hex(userkey_full[32:]))

        return userkeys


def decrypt_book(book: KoboBook, lib: KoboLibrary) -> int:
    """Decrypt a Kobo book and save it to disk.

    Returns 0 on success, 1 on failure.
    """
    print(f"Converting {book.title}")

    if book.type == "drm-free":
        print("DRM-free book, conversion is not needed")
        import shutil

        outname = f"{_SANITIZE_FILENAME_RE.sub('_', book.title)}.epub"
        shutil.copyfile(book.filename, outname)
        print(f"Book saved as {os.path.join(os.getcwd(), outname)}")
        return 0

    # Sanitize output filename
    outname = f"{_SANITIZE_FILENAME_RE.sub('_', book.title)}.epub"

    zin = zipfile.ZipFile(book.filename, "r")

    for userkey in lib.userkeys:
        print(f"Trying key: {userkey.hex()}")
        try:
            zout = zipfile.ZipFile(outname, "w", zipfile.ZIP_DEFLATED)
            for filename in zin.namelist():
                contents = zin.read(filename)
                if filename in book.encryptedfiles:
                    file_obj = book.encryptedfiles[filename]
                    contents = file_obj.decrypt(userkey, contents)
                    file_obj.check(contents)
                zout.writestr(filename, contents)
            zout.close()
            print("Decryption succeeded.")
            print(f"Book saved as {os.path.join(os.getcwd(), outname)}")
            zin.close()
            return 0

        except ValueError:
            print("Decryption failed.")
            zout.close()
            try:
                os.remove(outname)
            except OSError:
                pass

    zin.close()
    return 1
