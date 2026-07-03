"""Tests for single file decryption (AES-CBC + PKCS#7 unpad + raw deflate)."""

import os
import zipfile
from pathlib import Path


def _create_encrypted_file(plaintext: bytes, content_key: bytes) -> bytes:
    """Create ADEPT-encrypted file data from plaintext and AES key.

    Pipeline: raw deflate compress -> AES-128-CBC encrypt (IV prepended).
    """
    from Cryptodome.Cipher import AES

    # Step 1: Raw deflate compress (no zlib header)
    c = __import__("zlib").compressobj(wbits=-__import__("zlib").MAX_WBITS)
    compressed = c.compress(plaintext) + c.flush()

    # Step 2: AES-128-CBC encrypt with random IV
    iv = __import__("os").urandom(16)
    cipher = AES.new(content_key, AES.MODE_CBC, iv=iv)

    # PKCS#7 pad the compressed data
    pad_len = 16 - (len(compressed) % 16)
    padded = compressed + bytes([pad_len] * pad_len)

    ciphertext = cipher.encrypt(padded)

    # Return IV + ciphertext (as stored in ADEPT EPUB)
    return iv + ciphertext


def _load_reference_gif() -> bytes:
    """Load the reference GIF from the decrypted EPUB."""
    ref_epub = Path("Making a Career in Dictatorship-decrypted.epub")
    if not ref_epub.exists():
        raise __import__("unittest").SkipTest("Reference decrypted EPUB not found")

    with zipfile.ZipFile(ref_epub) as zf:
        for name in zf.namelist():
            if "graphic-004.gif" in name:
                return zf.read(name)
    raise __import__("unittest").SkipTest("GIF not found in reference EPUB")


def _load_encrypted_gif() -> bytes:
    """Load the encrypted GIF from the encrypted EPUB."""
    enc_epub = Path("Making a Career in Dictatorship-encrypted.epub")
    if not enc_epub.exists():
        raise __import__("unittest").SkipTest("Encrypted EPUB not found")

    with zipfile.ZipFile(enc_epub) as zf:
        for name in zf.namelist():
            if "graphic-004.gif" in name:
                return zf.read(name)
    raise __import__("unittest").SkipTest("GIF not found in encrypted EPUB")


class TestDecryptFile:
    """Tests for decrypting a single file from an ADEPT EPUB."""

    def test_decrypt_gif_matches_reference(self):
        """Given encrypted GIF data and correct content key, produces 15313 bytes matching reference."""
        adl_db = Path("~/.adl/adl.db").expanduser()
        encrypted_epub = Path("Making a Career in Dictatorship-encrypted.epub")

        if not adl_db.exists() or not encrypted_epub.exists():
            raise __import__("unittest").SkipTest("ADL DB or encrypted EPUB not found")

        from adl.adept import (
            decrypt_content_key,
            decrypt_file,
            extract_rights_and_encryption,
            load_private_key,
        )

        rights_data, _ = extract_rights_and_encryption(str(encrypted_epub))
        private_key = load_private_key(str(adl_db), rights_data["user_id"])
        content_key = decrypt_content_key(
            __import__("base64").b64decode(rights_data["encrypted_key_b64"]),
            private_key,
        )

        encrypted_gif = _load_encrypted_gif()
        plaintext = decrypt_file(encrypted_gif, content_key)

        # Should produce exactly 15313 bytes (confirmed by spike probe)
        assert len(plaintext) == 15313

        # Verify it's a valid GIF file
        assert plaintext[:3] == b"GIF"

    def test_decrypt_gif_matches_reference_bytes(self):
        """Given encrypted GIF data and correct content key, matches reference EPUB byte-for-byte."""
        adl_db = Path("~/.adl/adl.db").expanduser()
        encrypted_epub = Path("Making a Career in Dictatorship-encrypted.epub")

        if not adl_db.exists() or not encrypted_epub.exists():
            raise __import__("unittest").SkipTest("ADL DB or encrypted EPUB not found")

        from adl.adept import (
            decrypt_content_key,
            decrypt_file,
            extract_rights_and_encryption,
            load_private_key,
        )

        rights_data, _ = extract_rights_and_encryption(str(encrypted_epub))
        private_key = load_private_key(str(adl_db), rights_data["user_id"])
        content_key = decrypt_content_key(
            __import__("base64").b64decode(rights_data["encrypted_key_b64"]),
            private_key,
        )

        encrypted_gif = _load_encrypted_gif()
        plaintext = decrypt_file(encrypted_gif, content_key)

        # Compare with reference decrypted EPUB
        ref_gif = _load_reference_gif()
        assert plaintext == ref_gif

    def test_decrypt_xhtml_produces_valid_xml(self):
        """Given encrypted XHTML data and correct content key, produces valid XML."""
        adl_db = Path("~/.adl/adl.db").expanduser()
        encrypted_epub = Path("Making a Career in Dictatorship-encrypted.epub")

        if not adl_db.exists() or not encrypted_epub.exists():
            raise __import__("unittest").SkipTest("ADL DB or encrypted EPUB not found")

        from adl.adept import (
            decrypt_content_key,
            decrypt_file,
            extract_rights_and_encryption,
            load_private_key,
        )

        rights_data, _ = extract_rights_and_encryption(str(encrypted_epub))
        private_key = load_private_key(str(adl_db), rights_data["user_id"])
        content_key = decrypt_content_key(
            __import__("base64").b64decode(rights_data["encrypted_key_b64"]),
            private_key,
        )

        # Find an encrypted XHTML file from the EPUB
        with zipfile.ZipFile(encrypted_epub) as zf:
            for name in zf.namelist():
                if name.endswith(".xhtml"):
                    encrypted_xhtml = zf.read(name)
                    plaintext = decrypt_file(encrypted_xhtml, content_key)

                    # Should produce valid XML starting with <html
                    text = plaintext.decode("utf-8")
                    assert "<html" in text.lower() or "<?xml" in text
                    return

        raise __import__("unittest").SkipTest("No XHTML files found in encrypted EPUB")

    def test_decrypt_roundtrip(self, tmp_path):
        """Given any plaintext, encrypting then decrypting produces the original."""
        from adl.adept import decrypt_file

        content_key = (
            b"\x01\x02\x03\x04\x05\x06\x07\x08\x09\x0a\x0b\x0c\x0d\x0e\x0f\x10"
        )
        plaintext = b"<html><body>Hello World!</body></html>"

        encrypted = _create_encrypted_file(plaintext, content_key)
        result = decrypt_file(encrypted, content_key)

        assert result == plaintext

    def test_decrypt_roundtrip_binary(self, tmp_path):
        """Given binary data (like a GIF), encrypting then decrypting produces the original."""
        from adl.adept import decrypt_file

        content_key = (
            b"\xaa\xbb\xcc\xdd\xee\xff\x00\x11\x22\x33\x44\x55\x66\x77\x88\x99"
        )
        # Simulate a small GIF header + image data
        plaintext = b"GIF89a" + os.urandom(500)

        encrypted = _create_encrypted_file(plaintext, content_key)
        result = decrypt_file(encrypted, content_key)

        assert result == plaintext

    def test_decrypt_empty_file(self, tmp_path):
        """Given empty plaintext, encrypting then decrypting produces empty bytes."""
        from adl.adept import decrypt_file

        content_key = (
            b"\x01\x02\x03\x04\x05\x06\x07\x08\x09\x0a\x0b\x0c\x0d\x0e\x0f\x10"
        )
        plaintext = b""

        encrypted = _create_encrypted_file(plaintext, content_key)
        result = decrypt_file(encrypted, content_key)

        assert result == plaintext
