#!/usr/bin/env python3
"""Test if decrypted output is zlib/deflate compressed."""

import base64
import sqlite3
import zipfile
from xml.etree import ElementTree as ET
import zlib

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding as asym_padding
from Cryptodome.Cipher import AES


ENCRYPTED = "/Users/kris/Source/adl/Making a Career in Dictatorship-encrypted.epub"
DECRYPTED = "/Users/kris/Source/adl/Making a Career in Dictatorship-decrypted.epub"
ADL_DB = "/Users/kris/.adl/adl.db"


def main():
    conn = sqlite3.connect(ADL_DB)
    rows = conn.execute("SELECT license_priv FROM users").fetchall()
    lic_key = serialization.load_der_private_key(
        base64.b64decode(rows[0][0]), password=None
    )
    conn.close()

    with zipfile.ZipFile(ENCRYPTED) as zf:
        root = ET.fromstring(zf.read("META-INF/rights.xml"))
        for elem in root.iter():
            tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
            if tag == "encryptedKey" and elem.get("keyInfo") == "user":
                enc_key_b64 = "".join(elem.itertext()).strip()

        enc_xhtml = zf.read("OEBPS/isbn-9780197831229-front-matter-part-2.xhtml")
        enc_gif = zf.read("OEBPS/media/isbn-9780197831229-book-part-2-graphic-004.gif")

    aes_key = lic_key.decrypt(base64.b64decode(enc_key_b64), asym_padding.PKCS1v15())
    iv_zeros = b"\x00" * 16

    ref_xhtml = zipfile.ZipFile(DECRYPTED).read(
        "OEBPS/isbn-9780197831229-front-matter-part-2.xhtml"
    )
    ref_gif = zipfile.ZipFile(DECRYPTED).read(
        "OEBPS/media/isbn-9780197831229-book-part-2-graphic-004.gif"
    )

    # Test 1: IV=zeros, decrypt then try deflate decompression
    print("=== IV=zeros ===")
    for name, enc_data, ref in [
        ("XHTML", enc_xhtml, ref_xhtml),
        ("GIF", enc_gif, ref_gif),
    ]:
        cipher = AES.new(aes_key, AES.MODE_CBC, iv=iv_zeros)
        dec = cipher.decrypt(enc_data)
        pad_len = dec[-1]
        if 1 <= pad_len <= 16 and all(b == pad_len for b in dec[-pad_len:]):
            dec = dec[:-pad_len]

        print(f"\n{name}: decrypted={len(dec)} bytes")
        for wbits_name, wbits in [("zlib", 15), ("raw deflate", -zlib.MAX_WBITS)]:
            try:
                decomp = zlib.decompress(dec, wbits=wbits)
                matches = decomp == ref
                print(
                    f"  {wbits_name}: -> {len(decomp)} bytes {'*** MATCHES ***' if matches else 'NO MATCH'}"
                )
                if not matches and name == "XHTML":
                    preview = decomp[:80]
                    try:
                        printable = "".join(
                            chr(b) if 32 <= b < 127 else "." for b in preview
                        )
                        print(f"    Preview: {printable}")
                    except Exception:
                        pass
            except Exception as e:
                print(f"  {wbits_name}: failed ({e})")

    # Test 2: IV=first16 bytes, decrypt then try deflate decompression
    print("\n\n=== IV=first16 ===")
    for name, enc_data, ref in [
        ("XHTML", enc_xhtml, ref_xhtml),
        ("GIF", enc_gif, ref_gif),
    ]:
        iv = enc_data[:16]
        ct = enc_data[16:]
        cipher = AES.new(aes_key, AES.MODE_CBC, iv=iv)
        dec = cipher.decrypt(ct)
        pad_len = dec[-1]
        if 1 <= pad_len <= 16 and all(b == pad_len for b in dec[-pad_len:]):
            dec = dec[:-pad_len]

        print(f"\n{name}: decrypted={len(dec)} bytes")
        for wbits_name, wbits in [("zlib", 15), ("raw deflate", -zlib.MAX_WBITS)]:
            try:
                decomp = zlib.decompress(dec, wbits=wbits)
                matches = decomp == ref
                print(
                    f"  {wbits_name}: -> {len(decomp)} bytes {'*** MATCHES ***' if matches else 'NO MATCH'}"
                )
                if not matches and name == "XHTML":
                    preview = decomp[:80]
                    try:
                        printable = "".join(
                            chr(b) if 32 <= b < 127 else "." for b in preview
                        )
                        print(f"    Preview: {printable}")
                    except Exception:
                        pass
            except Exception as e:
                print(f"  {wbits_name}: failed ({e})")


if __name__ == "__main__":
    main()
