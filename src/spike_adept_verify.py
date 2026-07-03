#!/usr/bin/env python3
"""Verify which key produces correct decryption, comparing against known-good output."""

import base64
import sqlite3
import zipfile
from xml.etree import ElementTree as ET

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding as asym_padding
from Cryptodome.Cipher import AES


ENCRYPTED = "/Users/kris/Source/adl/Making a Career in Dictatorship-encrypted.epub"
DECRYPTED = "/Users/kris/Source/adl/Making a Career in Dictatorship-decrypted.epub"
ADL_DB = "/Users/kris/.adl/adl.db"


def load_keys():
    conn = sqlite3.connect(ADL_DB)
    rows = conn.execute("SELECT auth_priv, license_priv FROM users").fetchall()
    conn.close()

    auth_key = serialization.load_der_private_key(
        base64.b64decode(rows[0][0]), password=None
    )
    lic_key = serialization.load_der_private_key(
        base64.b64decode(rows[0][1]), password=None
    )
    return auth_key, lic_key


def get_encrypted_key():
    with zipfile.ZipFile(ENCRYPTED) as zf:
        root = ET.fromstring(zf.read("META-INF/rights.xml"))
    for elem in root.iter():
        tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
        if tag == "encryptedKey" and elem.get("keyInfo") == "user":
            return "".join(elem.itertext()).strip()
    raise ValueError("Could not find encrypted key in rights.xml")


def decrypt_file(encrypted_data: bytes, aes_key: bytes) -> bytes:
    """Decrypt with AES-128-CBC, IV=zeros, PKCS#7 unpadding."""
    iv = b"\x00" * 16
    cipher = AES.new(aes_key, AES.MODE_CBC, iv=iv)
    plaintext = cipher.decrypt(encrypted_data)
    pad_len = plaintext[-1]
    if 1 <= pad_len <= 16 and all(b == pad_len for b in plaintext[-pad_len:]):
        plaintext = plaintext[:-pad_len]
    return plaintext


def main():
    auth_key, lic_key = load_keys()
    enc_key_b64 = get_encrypted_key()
    enc_key_bytes = base64.b64decode(enc_key_b64)

    # RSA-decrypt content key with each private key
    auth_decrypted = auth_key.decrypt(enc_key_bytes, asym_padding.PKCS1v15())
    lic_decrypted = lic_key.decrypt(enc_key_bytes, asym_padding.PKCS1v15())

    print("=" * 60)
    print("KEY COMPARISON")
    print("=" * 60)
    print(
        f"auth_priv decrypted: {len(auth_decrypted)} bytes -> AES key = {auth_decrypted[:16].hex()}"
    )
    print(
        f"license_priv decrypted: {len(lic_decrypted)} bytes -> full output = {lic_decrypted.hex()}"
    )

    # Load reference files from the known-good decrypted EPUB
    with zipfile.ZipFile(DECRYPTED) as zdec:
        ref_gif = zdec.read(
            "OEBPS/media/isbn-9780197831229-book-part-2-graphic-004.gif"
        )
        ref_xhtml = zdec.read("OEBPS/isbn-9780197831229-front-matter-part-2.xhtml")

    # Load encrypted versions from the EPUB
    with zipfile.ZipFile(ENCRYPTED) as zenc:
        enc_gif = zenc.read(
            "OEBPS/media/isbn-9780197831229-book-part-2-graphic-004.gif"
        )
        enc_xhtml = zenc.read("OEBPS/isbn-9780197831229-front-matter-part-2.xhtml")

    print(f"\nReference GIF: {len(ref_gif)} bytes (ZIP DEFLATED)")
    print(f"Encrypted GIF: {len(enc_gif)} bytes (ZIP STORED)")
    print(f"Reference XHTML: {len(ref_xhtml)} bytes (ZIP DEFLATED)")
    print(f"Encrypted XHTML: {len(enc_xhtml)} bytes (ZIP STORED)")

    # --- Test 1: GIF with license_priv key ---
    dec_gif_lic = decrypt_file(enc_gif, lic_decrypted)
    matches_gif_lic = dec_gif_lic == ref_gif
    print(
        f"\nGIF + license_priv (IV=zeros): {len(dec_gif_lic)} bytes {'*** MATCHES ***' if matches_gif_lic else 'NO MATCH'}"
    )

    # --- Test 2: GIF with auth_priv key (first 16 bytes as AES key) ---
    dec_gif_auth = decrypt_file(enc_gif, auth_decrypted[:16])
    matches_gif_auth = dec_gif_auth == ref_gif
    print(
        f"GIF + auth_priv[:16] (IV=zeros): {len(dec_gif_auth)} bytes {'*** MATCHES ***' if matches_gif_auth else 'NO MATCH'}"
    )

    # --- Test 3: XHTML with license_priv key ---
    dec_xhtml_lic = decrypt_file(enc_xhtml, lic_decrypted)
    matches_xhtml_lic = dec_xhtml_lic == ref_xhtml
    print(
        f"XHTML + license_priv (IV=zeros): {len(dec_xhtml_lic)} bytes {'*** MATCHES ***' if matches_xhtml_lic else 'NO MATCH'}"
    )

    # --- Test 4: XHTML with auth_priv key ---
    dec_xhtml_auth = decrypt_file(enc_xhtml, auth_decrypted[:16])
    matches_xhtml_auth = dec_xhtml_auth == ref_xhtml
    print(
        f"XHTML + auth_priv[:16] (IV=zeros): {len(dec_xhtml_auth)} bytes {'*** MATCHES ***' if matches_xhtml_auth else 'NO MATCH'}"
    )

    # --- If XHTML doesn't match raw, check if it needs zlib decompression ---
    if not matches_xhtml_lic:
        import zlib

        try:
            decompressed = zlib.decompress(dec_xhtml_lic, -zlib.MAX_WBITS)
            print(
                f"XHTML + license_priv after zlib: {len(decompressed)} bytes {'*** MATCHES ***' if decompressed == ref_xhtml else 'NO MATCH'}"
            )
        except Exception as e:
            print(f"  Not zlib-compressible: {e}")

    # --- Test with actual IV prepended (first 16 bytes) instead of zeros ---
    print("\n--- Testing with IV from first 16 bytes of encrypted data ---")
    for key_name, aes_key in [
        ("license", lic_decrypted),
        ("auth[:16]", auth_decrypted[:16]),
    ]:
        iv = enc_gif[:16]
        ciphertext = enc_gif[16:]
        cipher = AES.new(aes_key, AES.MODE_CBC, iv=iv)
        result = cipher.decrypt(ciphertext)
        pad_len = result[-1]
        if 1 <= pad_len <= 16 and all(b == pad_len for b in result[-pad_len:]):
            result = result[:-pad_len]
        matches = result == ref_gif
        print(
            f"  GIF + {key_name} (IV=first16): {len(result)} bytes {'*** MATCHES ***' if matches else 'NO MATCH'}"
        )

    # --- Summary ---
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)

    results = [
        ("GIF", "license_priv (zeros IV)", dec_gif_lic, ref_gif),
        ("GIF", "auth_priv[:16] (zeros IV)", dec_gif_auth, ref_gif),
        ("XHTML", "license_priv (zeros IV)", dec_xhtml_lic, ref_xhtml),
        ("XHTML", "auth_priv[:16] (zeros IV)", dec_xhtml_auth, ref_xhtml),
    ]

    for name, desc, dec, ref in results:
        status = "PASS" if dec == ref else f"FAIL ({len(dec)} vs {len(ref)})"
        print(f"  {name} + {desc}: {status}")


if __name__ == "__main__":
    main()
