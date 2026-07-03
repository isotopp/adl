#!/usr/bin/env python3
"""Compare decrypted XHTML with reference."""

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

    with zipfile.ZipFile(
        "/Users/kris/Source/adl/Making a Career in Dictatorship-encrypted.epub"
    ) as zf:
        root = ET.fromstring(zf.read("META-INF/rights.xml"))
        for elem in root.iter():
            tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
            if tag == "encryptedKey" and elem.get("keyInfo") == "user":
                enc_key_b64 = "".join(elem.itertext()).strip()

        enc_xhtml = zf.read("OEBPS/isbn-9780197831229-front-matter-part-2.xhtml")

    aes_key = lic_key.decrypt(base64.b64decode(enc_key_b64), asym_padding.PKCS1v15())

    # Decrypt XHTML with IV=first16
    iv = enc_xhtml[:16]
    ct = enc_xhtml[16:]
    cipher = AES.new(aes_key, AES.MODE_CBC, iv=iv)
    dec = cipher.decrypt(ct)
    pad_len = dec[-1]
    if 1 <= pad_len <= 16 and all(b == pad_len for b in dec[-pad_len:]):
        dec = dec[:-pad_len]

    print(f"Decrypted XHTML (after AES): {len(dec)} bytes")

    # Try raw deflate decompression
    decomp = zlib.decompress(dec, -zlib.MAX_WBITS)
    print(f"After raw deflate: {len(decomp)} bytes")

    ref = zipfile.ZipFile(
        "/Users/kris/Source/adl/Making a Career in Dictatorship-decrypted.epub"
    ).read("OEBPS/isbn-9780197831229-front-matter-part-2.xhtml")
    print(f"Reference XHTML: {len(ref)} bytes (after ZIP decompression)")

    print(f"\nMatch? {decomp == ref}")

    # Show first 150 chars of each for comparison
    print("\nDecompressed preview:")
    try:
        print(decomp[:200].decode("utf-8", errors="replace"))
    except Exception:
        pass

    print("\nReference preview:")
    try:
        print(ref[:200].decode("utf-8", errors="replace"))
    except Exception:
        pass


if __name__ == "__main__":
    main()
