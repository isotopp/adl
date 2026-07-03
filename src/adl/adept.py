"""Adobe ADEPT EPUB decryption using ADL authorization database keys.

This module is fully self-contained and does not import from obok/.
"""

import argparse
import base64
import os
import sqlite3
import sys
import zipfile
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from Cryptodome.Cipher import AES
from xml.etree import ElementTree
from cryptography.hazmat.primitives.serialization import load_der_private_key


def extract_rights_and_encryption(encrypted_epub_path: str):
    """Extract and parse META-INF/rights.xml and META-INF/encryption.xml from an EPUB.

    Opens the EPUB as a ZIP archive, reads rights.xml and encryption.xml,
    and parses their contents.

    Args:
        encrypted_epub_path: Path to the ADEPT-protected EPUB file.

    Returns:
        A tuple of (rights_data, encryption_map):
          - rights_data: dict with {user_id, resource_id, encrypted_key_b64},
            or None if rights.xml is not found.
          - encryption_map: dict mapping file URIs to resource IDs,
            or empty dict if encryption.xml is not found.
    """
    rights_data = None
    encryption_map = {}

    with zipfile.ZipFile(encrypted_epub_path) as zf:
        if "META-INF/rights.xml" in zf.namelist():
            rights_xml = zf.read("META-INF/rights.xml")
            root = ElementTree.fromstring(rights_xml)

            user_id = None
            resource_id = None
            encrypted_key_b64 = None

            for elem in root.iter():
                tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag

                if tag == "user":
                    user_id = ("".join(elem.itertext())).strip()
                elif tag == "resource":
                    resource_id = ("".join(elem.itertext())).strip()
                elif tag == "encryptedKey" and elem.get("keyInfo") == "user":
                    encrypted_key_b64 = ("".join(elem.itertext())).strip()

            if user_id and resource_id and encrypted_key_b64:
                rights_data = {
                    "user_id": user_id,
                    "resource_id": resource_id,
                    "encrypted_key_b64": encrypted_key_b64,
                }

        if "META-INF/encryption.xml" in zf.namelist():
            encryption_xml = zf.read("META-INF/encryption.xml")
            root = ElementTree.fromstring(encryption_xml)

            for enc_elem in root.iter():
                tag = (
                    enc_elem.tag.split("}")[-1] if "}" in enc_elem.tag else enc_elem.tag
                )
                if tag == "EncryptedData":
                    cipher_ref = None
                    resource_uuid = None

                    for child in enc_elem.iter():
                        child_tag = (
                            child.tag.split("}")[-1] if "}" in child.tag else child.tag
                        )
                        if child_tag == "CipherReference":
                            cipher_ref = child.get("URI")
                        elif child_tag == "resource":
                            resource_uuid = ("".join(child.itertext())).strip()

                    if cipher_ref and resource_uuid:
                        encryption_map[cipher_ref] = resource_uuid

    return rights_data, encryption_map


def load_private_key(db_path: str, user_id: str) -> rsa.RSAPrivateKey:
    """Load the RSA private key from an ADL database for a given user.

    Keys are stored as base64-encoded DER blobs (not PEM).
    Tries license_priv first; falls back to auth_priv if decryption fails.

    Args:
        db_path: Path to the ADL SQLite database file.
        user_id: The user_id matching <user> in rights.xml (e.g. urn:uuid:...).

    Returns:
        An rsa.RSAPrivateKey object from the cryptography library.

    Raises:
        ValueError: If no matching user is found or keys cannot be loaded.
    """
    conn = sqlite3.connect(db_path)
    conn.text_factory = str
    c = conn.cursor()

    rows = c.execute(
        "SELECT license_priv, auth_priv FROM users WHERE user_id = ?", (user_id,)
    ).fetchone()

    conn.close()

    if rows is None:
        raise ValueError(f"No user found with user_id={user_id}")

    license_priv_b64, auth_priv_b64 = rows[0], rows[1]

    # Try license_priv first (per plan: it gives a clean 16-byte AES key)
    if license_priv_b64:
        try:
            der_bytes = base64.b64decode(license_priv_b64)
            key = load_der_private_key(der_bytes, password=None)
            if isinstance(key, rsa.RSAPrivateKey):
                return key
        except Exception:
            pass

    # Fall back to auth_priv
    if auth_priv_b64:
        try:
            der_bytes = base64.b64decode(auth_priv_b64)
            key = load_der_private_key(der_bytes, password=None)
            if isinstance(key, rsa.RSAPrivateKey):
                return key
        except Exception:
            pass

    raise ValueError(
        f"User {user_id} exists but no usable private key found "
        "(license_priv and auth_priv are missing or invalid)"
    )


def decrypt_content_key(
    encrypted_key_bytes: bytes, private_key: rsa.RSAPrivateKey
) -> bytes:
    """RSA-decrypt the AES content key from rights.xml.

    Uses PKCS#1 v1.5 padding (confirmed by spike probe).
    Returns 16-byte AES-128 key.

    Args:
        encrypted_key_bytes: Base64-decoded RSA ciphertext from rights.xml.
        private_key: The RSA private key loaded from the ADL database.

    Returns:
        16-byte AES-128 content key.
    """
    return private_key.decrypt(encrypted_key_bytes, padding.PKCS1v15())


def decrypt_file(encrypted_data: bytes, content_key: bytes) -> bytes:
    """Decrypt a single file from an ADEPT EPUB.

    Pipeline (verified by spike probe):
      1. AES-128-CBC with IV = first 16 bytes of encrypted_data
      2. PKCS#7 unpadding
      3. Raw deflate decompression (wbits=-zlib.MAX_WBITS, no zlib header)

    Args:
        encrypted_data: IV (first 16 bytes) + AES-CBC ciphertext.
        content_key: 16-byte AES-128 key from decrypt_content_key().

    Returns:
        The original plaintext bytes.
    """
    iv = encrypted_data[:16]
    ciphertext = encrypted_data[16:]

    dec = AES.new(content_key, AES.MODE_CBC, iv=iv).decrypt(ciphertext)

    # PKCS#7 unpadding
    pad_len = dec[-1]
    if 1 <= pad_len <= 16 and all(b == pad_len for b in dec[-pad_len:]):
        dec = dec[:-pad_len]

    # Raw deflate decompress (all files are raw-deflate compressed before AES)
    return __import__("zlib").decompress(dec, wbits=-__import__("zlib").MAX_WBITS)


def decrypt_epub(encrypted_epub_path: str, output_epub_path: str, adl_db_path: str):
    """Decrypt an entire ADEPT-protected EPUB and write the decrypted version.

    Pipeline:
      1. Extract rights.xml and encryption.xml from encrypted EPUB
      2. Load RSA private key from ADL database
      3. Decrypt AES content key from rights.xml
      4. For each encrypted file, decrypt and write to output EPUB

    Args:
        encrypted_epub_path: Path to the ADEPT-protected EPUB file.
        output_epub_path: Path where the decrypted EPUB will be written.
        adl_db_path: Path to the ADL SQLite database file.

    Raises:
        ValueError: If rights.xml is missing or decryption fails.
    """
    rights_data, encryption_map = extract_rights_and_encryption(encrypted_epub_path)

    if not rights_data:
        raise ValueError(f"No META-INF/rights.xml found in {encrypted_epub_path}")

    private_key = load_private_key(adl_db_path, rights_data["user_id"])
    content_key = decrypt_content_key(
        base64.b64decode(rights_data["encrypted_key_b64"]), private_key
    )

    with zipfile.ZipFile(encrypted_epub_path) as enc_zf:
        file_map = {}  # file_name -> encrypted_data

        for cipher_ref in encryption_map:
            # Extract file name from URI (e.g., "OEBPS/Chapter1.xhtml" -> same)
            file_name = cipher_ref.split("#")[-1] if "#" in cipher_ref else cipher_ref

            try:
                encrypted_data = enc_zf.read(file_name)
                file_map[file_name] = encrypted_data
            except KeyError:
                # File not in encryption.xml — skip (e.g., mimetype, images)
                pass

        # Build output EPUB
        with zipfile.ZipFile(
            output_epub_path, "w", compression=zipfile.ZIP_DEFLATED
        ) as out_zf:
            for name in enc_zf.namelist():
                if name == "mimetype":
                    # mimetype must be stored uncompressed (ZIP_STORED) per EPUB spec
                    data = enc_zf.read(name)
                    out_zf.writestr(
                        zipfile.ZipInfo("mimetype"),
                        data,
                        compress_type=zipfile.ZIP_STORED,
                    )
                elif name in file_map:
                    # This is an encrypted file — decrypt it
                    decrypted = decrypt_file(file_map[name], content_key)
                    out_zf.writestr(name, decrypted)
                else:
                    # Not encrypted — copy as-is (e.g., mimetype, images)
                    data = enc_zf.read(name)
                    out_zf.writestr(name, data)


def build_parser():
    """Build the argument parser for adl-decode."""
    parser = argparse.ArgumentParser(
        description="Decrypt ADEPT-protected EPUB files using ADL database keys."
    )
    parser.add_argument(
        "epubs",
        nargs="*",
        help="EPUB files to decrypt.",
    )
    parser.add_argument(
        "--adl-database",
        default=os.path.join(os.environ.get("HOME", ""), ".adl", "adl.db"),
        help="Path to the ADL authorization database (default: ~/.adl/adl.db).",
    )
    parser.add_argument(
        "--output-directory",
        default="./epub",
        help="Directory to write decrypted EPUBs (default: ./epub).",
    )
    return parser


def main(argv=None):
    """Main entry point for adl-decode CLI.

    Parses arguments, creates output directory, and returns exit code.
    Decryption logic is implemented in subsequent tickets.

    Returns:
        int: 0 on success, 1 if no EPUB files provided.
    """
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.epubs:
        parser.print_help()
        return 1

    os.makedirs(args.output_directory, exist_ok=True)

    return 0


if __name__ == "__main__":
    sys.exit(main())
