#!/usr/bin/env python3
"""Test decryption pattern across different file types."""

import base64
import sqlite3
import zipfile
from xml.etree import ElementTree as ET
import zlib

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding as asym_padding
from Cryptodome.Cipher import AES


def main():
    conn = sqlite3.connect("/Users/kris/.adl/adl.db")
    lic_key = serialization.load_der_private_key(
        base64.b64decode(conn.execute("SELECT license_priv FROM users").fetchone()[0]),
        password=None,
    )
    conn.close()

    epub_path = "/Users/kris/Source/adl/Making a Career in Dictatorship-encrypted.epub"

    with zipfile.ZipFile(epub_path) as zf:
        root = ET.fromstring(zf.read("META-INF/rights.xml"))
        for elem in root.iter():
            tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
            if tag == "encryptedKey" and elem.get("keyInfo") == "user":
                enc_key_b64 = "".join(elem.itertext()).strip()

        aes_key = lic_key.decrypt(
            base64.b64decode(enc_key_b64), asym_padding.PKCS1v15()
        )

    test_files = [
        (
            "OEBPS/media/isbn-9780197831229-book-part-2-graphic-004.gif",
            "binary (GIF)",
        ),
        (
            "OEBPS/isbn-9780197831229-front-matter-part-2.xhtml",
            "text (XHTML)",
        ),
        ("OEBPS/media/inline-audio.svg", "text (SVG)"),
    ]

    with zipfile.ZipFile(epub_path) as zf:
        for name, desc in test_files:
            enc = zf.read(name)

            # IV=first16 + AES-CBC decrypt
            iv = enc[:16]
            ct = enc[16:]
            cipher = AES.new(aes_key, AES.MODE_CBC, iv=iv)
            dec = cipher.decrypt(ct)
            pad_len = dec[-1]
            if 1 <= pad_len <= 16 and all(b == pad_len for b in dec[-pad_len:]):
                dec = dec[:-pad_len]

            # Try deflate decompression
            try:
                decomp = zlib.decompress(dec, -zlib.MAX_WBITS)
                print(f"{name} ({desc}): AES+deflate OK -> {len(decomp)} bytes")
            except Exception:
                print(f"{name} ({desc}): AES only (no deflate): {len(dec)} bytes")


if __name__ == "__main__":
    main()
