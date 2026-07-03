"""Tests for obok.models module."""

import os
import sqlite3
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from Cryptodome.Cipher import AES

from adl.obok.models import (
    ENCRYPTIONError,
    KoboBook,
    KoboFile,
    KoboLibrary,
    decrypt_book,
)


class TestKoboFile:
    """Tests for the KoboFile class."""

    def _make_encrypted_content(self, plaintext: bytes, key: bytes) -> bytes:
        """Helper to encrypt content with AES-ECB + PKCS#7 padding."""
        cipher = AES.new(key, AES.MODE_ECB)
        # Pad plaintext to block size
        pad_len = 16 - (len(plaintext) % 16)
        padded = plaintext + bytes([pad_len] * pad_len)
        return cipher.encrypt(padded)

    def _make_user_key(self) -> bytes:
        """Generate a valid-length user key (16 bytes for AES-128)."""
        return os.urandom(16)

    def _make_page_key(self) -> bytes:
        """Generate a random page key (16 bytes for AES-128)."""
        return os.urandom(16)

    def test_decrypt_roundtrip(self):
        plaintext = b"hello world"
        userkey = self._make_user_key()
        # In Kobo, the stored "page key" is actually AES(userkey).encrypt(page_key)
        page_key = self._make_page_key()
        stored_key = AES.new(userkey, AES.MODE_ECB).encrypt(page_key)

        encrypted_content = self._make_encrypted_content(plaintext, page_key)

        file_obj = KoboFile("test.xhtml", "application/xhtml+xml", stored_key)
        decrypted = file_obj.decrypt(userkey, encrypted_content)

        assert decrypted == plaintext

    def test_decrypt_xml_roundtrip(self):
        xml_data = b'<?xml version="1.0" encoding="utf-8"?><html></html>'
        userkey = self._make_user_key()
        page_key = self._make_page_key()
        stored_key = AES.new(userkey, AES.MODE_ECB).encrypt(page_key)

        encrypted_content = self._make_encrypted_content(xml_data, page_key)

        file_obj = KoboFile("chapter.xhtml", "application/xhtml+xml", stored_key)
        decrypted = file_obj.decrypt(userkey, encrypted_content)

        assert decrypted == xml_data

    def test_check_xml_valid_utf8(self):
        xml_content = b'<?xml version="1.0"?><html><body>Hello</body></html>'
        file_obj = KoboFile("test.xhtml", "application/xhtml+xml", None)
        # Should not raise
        assert file_obj.check(xml_content) is True

    def test_check_xml_valid_utf8_with_bom(self):
        xml_content = b'\xef\xbb\xbf<?xml version="1.0"?><html></html>'
        file_obj = KoboFile("test.xhtml", "application/xhtml+xml", None)
        assert file_obj.check(xml_content) is True

    def test_check_xml_valid_utf16be(self):
        xml_content = b"\xfe\xff\x00<\x00?\x00x\x00m\x00l"
        file_obj = KoboFile("test.xhtml", "application/xhtml+xml", None)
        assert file_obj.check(xml_content) is True

    def test_check_xml_valid_utf16le(self):
        xml_content = b"\xff\xfe<\x00?\x00x\x00m\x00l\x00"
        file_obj = KoboFile("test.xhtml", "application/xhtml+xml", None)
        assert file_obj.check(xml_content) is True

    def test_check_xml_valid_doctype(self):
        xml_content = b"<!DOCTYPE html><html></html>"
        file_obj = KoboFile("test.xhtml", "application/xhtml+xml", None)
        assert file_obj.check(xml_content) is True

    def test_check_xml_invalid_non_ascii(self):
        # Content with non-ASCII in first 5 bytes (looks like failed decryption)
        xml_content = b"\x00\x80\xff\xfe\xfd<?xml..."
        file_obj = KoboFile("test.xhtml", "application/xhtml+xml", None)
        with pytest.raises(ValueError):
            file_obj.check(xml_content)

    def test_check_xml_invalid_bad_start(self):
        random_data = b"\x00\x01\x02\x03\x04\x05\x06\x07\x08\x09"
        file_obj = KoboFile("test.xhtml", "application/xhtml+xml", None)
        with pytest.raises(ValueError):
            file_obj.check(random_data)

    def test_check_jpeg_valid(self):
        jpeg_content = b"\xff\xd8\xff\xe0\x00\x10JFIF"
        file_obj = KoboFile("cover.jpg", "image/jpeg", None)
        assert file_obj.check(jpeg_content) is True

    def test_check_jpeg_invalid(self):
        not_jpeg = b"\x89PNG\r\n\x1a\n"  # PNG signature
        file_obj = KoboFile("cover.jpg", "image/jpeg", None)
        with pytest.raises(ValueError):
            file_obj.check(not_jpeg)

    def test_check_unknown_mimetype(self):
        content = b"some random data"
        file_obj = KoboFile("font.woff", "font/woff", None)
        # Unknown MIME types should not raise, just return False
        assert file_obj.check(content) is False


class TestKoboBook:
    """Tests for the KoboBook class."""

    def _create_test_epub(self, path: Path, has_drm_files: bool = True) -> None:
        """Create a minimal test EPUB/kepub structure."""
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr(
                "META-INF/container.xml",
                '<?xml version="1.0"?><container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles></container>',
            )
            zf.writestr(
                "OEBPS/content.opf",
                '<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" version="3.0"><manifest><item id="chapter1" href="chapter1.xhtml" media-type="application/xhtml+xml"/><item id="cover" href="cover.jpg" media-type="image/jpeg"/></manifest><spine><itemref idref="chapter1"/></spine></package>',
            )
            zf.writestr(
                "OEBPS/chapter1.xhtml",
                '<?xml version="1.0"?><html xmlns="http://www.w3.org/1999/xhtml"><body><p>Hello world</p></body></html>',
            )
            zf.writestr("OEBPS/cover.jpg", b"\xff\xd8\xff\xe0PNGplaceholder")

    @pytest.fixture()
    def temp_db(self, tmp_path: Path) -> tuple[str, sqlite3.Connection]:
        """Create a temporary Kobo-like SQLite database."""
        db_path = str(tmp_path / "Kobo.sqlite")
        conn = sqlite3.connect(db_path)
        c = conn.cursor()

        # Create tables mimicking Kobo schema
        c.execute(
            """CREATE TABLE content (
                ContentID TEXT PRIMARY KEY,
                Title TEXT,
                Attribution TEXT,
                Series TEXT
            )"""
        )
        c.execute(
            """CREATE TABLE content_keys (
                ContentID TEXT,
                VolumeID TEXT,
                ElementID TEXT,
                ElementKey BLOB,
                FOREIGN KEY(ContentID) REFERENCES content(ContentID)
            )"""
        )
        c.execute(
            """CREATE TABLE user (
                UserID TEXT PRIMARY KEY
            )"""
        )

        # Insert test data
        c.execute(
            "INSERT INTO user VALUES ('test-user-id-12345')",
        )
        c.execute(
            "INSERT INTO content VALUES ('vol-uuid-001', 'Test Book', 'Author Name', NULL)",
        )

        conn.commit()
        return db_path, conn

    def test_has_drm_kepub(self):
        cursor = MagicMock(spec=sqlite3.Cursor)
        book = KoboBook("vol-1", "Title", "/fake/path", "kepub", cursor)
        assert book.has_drm is True

    def test_has_drm_free_book(self):
        cursor = MagicMock(spec=sqlite3.Cursor)
        book = KoboBook("vol-2", "DRM-Free Title", "/fake/path", "drm-free", cursor)
        assert book.has_drm is False


class TestDecryptBook:
    """Tests for the decrypt_book function."""

    def _create_test_kepub_epub(self, path: Path, page_key: bytes) -> None:
        """Create a test kepub with encrypted content entries in DB mock."""
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr(
                "META-INF/container.xml",
                '<?xml version="1.0"?><container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles></container>',
            )
            zf.writestr(
                "OEBPS/content.opf",
                '<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf"><manifest><item id="ch" href="chapter.xhtml" media-type="application/xhtml+xml"/></manifest><spine><itemref idref="ch"/></spine></package>',
            )
            zf.writestr(
                "OEBPS/chapter.xhtml",
                '<?xml version="1.0"?><html xmlns="http://www.w3.org/1999/xhtml"><body><p>decrypted content</p></body></html>',
            )

    def _make_user_key(self) -> bytes:
        return os.urandom(16)

    def _make_page_key(self) -> bytes:
        return os.urandom(16)

    def test_decrypt_drm_free_book_copies_file(self, tmp_path: Path):
        """DRM-free books should be copied without modification."""
        book_path = tmp_path / "drmfree.epub"
        with zipfile.ZipFile(book_path, "w") as zf:
            zf.writestr("test.txt", "hello drm-free")

        cursor = MagicMock(spec=sqlite3.Cursor)
        book = KoboBook(
            "vol-drm-free", "DRM Free Book", str(book_path), "drm-free", cursor
        )

        lib_mock = MagicMock()
        old_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            result = decrypt_book(book, lib_mock)
        finally:
            os.chdir(old_cwd)

        assert result == 0
        # Check that an epub file was created with sanitized filename
        epub_files = [f for f in tmp_path.glob("*.epub") if f.name != book_path.name]
        assert len(epub_files) == 1
        # Verify content was copied correctly
        with zipfile.ZipFile(epub_files[0], "r") as zf:
            assert "test.txt" in zf.namelist()

    def test_decrypt_kepub_with_correct_key(self, tmp_path: Path):
        """Decrypt a kepub with the correct user key."""
        book_path = tmp_path / "encrypted.kepub"
        userkey = self._make_user_key()
        page_key = self._make_page_key()
        # In Kobo, stored_key = AES(userkey).encrypt(page_key)
        stored_key = AES.new(userkey, AES.MODE_ECB).encrypt(page_key)

        # Encrypt the chapter content with page_key
        plaintext = b'<?xml version="1.0"?><html xmlns="http://www.w3.org/1999/xhtml"><body>Hello</body></html>'
        cipher = AES.new(page_key, AES.MODE_ECB)
        pad_len = 16 - (len(plaintext) % 16)
        encrypted = cipher.encrypt(plaintext + bytes([pad_len] * pad_len))

        with zipfile.ZipFile(book_path, "w") as zf:
            # container.xml
            zf.writestr(
                "META-INF/container.xml",
                '<?xml version="1.0"?><container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles></container>',
            )
            # content.opf with encrypted chapter reference
            zf.writestr(
                "OEBPS/content.opf",
                '<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf"><manifest><item id="ch" href="chapter.xhtml" media-type="application/xhtml+xml"/></manifest><spine><itemref idref="ch"/></spine></package>',
            )
            # encrypted chapter
            zf.writestr("OEBPS/chapter.xhtml", encrypted)

        # Mock the book's encryptedfiles property with stored_key
        cursor = MagicMock(spec=sqlite3.Cursor)
        book = KoboBook("vol-enc", "Encrypted Book", str(book_path), "kepub", cursor)

        file_obj = KoboFile("OEBPS/chapter.xhtml", "application/xhtml+xml", stored_key)
        book._encrypted_files = {"OEBPS/chapter.xhtml": file_obj}

        lib_mock = MagicMock()
        lib_mock.userkeys = [userkey, os.urandom(16)]  # correct key first

        old_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            result = decrypt_book(book, lib_mock)
        finally:
            os.chdir(old_cwd)

        assert result == 0
        # Check that an epub file was created with sanitized filename
        epub_files = list(tmp_path.glob("*.epub"))
        assert len(epub_files) == 1


class TestKoboLibraryInit:
    """Tests for KoboLibrary initialization with no valid database."""

    @patch("adl.obok.models._is_windows", return_value=False)
    @patch("adl.obok.models._is_darwin", return_value=False)
    @patch("adl.obok.models._is_linux", return_value=False)
    def test_no_database_returns_empty_library(
        self, _mock_linux, _mock_darwin, _mock_windows
    ):
        """When no Kobo data directory is found, kobodir should be empty."""
        lib = KoboLibrary(
            device_path="/nonexistent/path",
            desktop_kobodir="",
        )
        assert lib.kobodir == ""

    @patch("adl.obok.models._is_windows", return_value=False)
    @patch("adl.obok.models._is_darwin", return_value=False)
    @patch("adl.obok.models._is_linux", return_value=False)
    def test_userkeys_empty_without_database(
        self, _mock_linux, _mock_darwin, _mock_windows
    ):
        """When no database and no MAC addresses found, userkeys should be empty."""
        lib = KoboLibrary(
            device_path="/nonexistent/path",
            desktop_kobodir="",
        )
        # Without any platform match, _get_mac_addresses returns only serials (empty)
        assert lib.userkeys == []


class TestENCRYPTIONError:
    """Tests for the ENCRYPTIONError exception class."""

    def test_is_exception(self):
        assert issubclass(ENCRYPTIONError, Exception)

    def test_can_be_raised_and_caught(self):
        with pytest.raises(ENCRYPTIONError):
            raise ENCRYPTIONError("test error message")
