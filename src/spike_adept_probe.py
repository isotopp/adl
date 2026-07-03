#!/usr/bin/env python3
"""Spike probe to investigate Adobe ADEPT encryption details.

Tests:
1. Which private key column (auth_priv vs license_priv) can decrypt the content key?
2. What RSA padding mode is used (PKCS1v15 vs OAEP)?
3. How are IVs stored in encrypted files?
4. Does zlib compression precede AES encryption?
"""

import base64
import sqlite3
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding as asym_padding
from Cryptodome.Cipher import AES


# --- Constants ---
ADL_DB = Path.home() / ".adl" / "adl.db"
ENCRYPTED_EPUB = (
    Path(__file__).parent.parent / "Making a Career in Dictatorship-encrypted.epub"
)
DECRYPTED_EPUB = (
    Path(__file__).parent.parent / "Making a Career in Dictatorship-decrypted.epub"
)

NS_ADEPT = "http://ns.adobe.com/adept"
NS_XMLENC = "http://www.w3.org/2001/04/xmlenc#"
NS_XMLSIG = "http://www.w3.org/2000/09/xmldsig#"


# --- Helpers ---


def parse_epub_xml(epub_path: str, xml_path: str):
    """Extract and parse an XML file from within an EPUB."""
    with zipfile.ZipFile(epub_path) as zf:
        raw = zf.read(xml_path)
    return ET.fromstring(raw)


def load_private_keys(db_path: str):
    """Load RSA private keys from ADL authorization database.

    Keys are stored as base64-encoded DER blobs in the DB, not PEM.
    """
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    rows = cursor.execute(
        "SELECT user_id, auth_priv, license_priv FROM users"
    ).fetchall()
    keys = {}
    for user_id, auth_b64, license_b64 in rows:
        if isinstance(auth_b64, bytes):
            auth_b64 = auth_b64.decode("utf-8", errors="replace")

        # Try DER first (base64-encoded raw ASN.1/DER)
        try:
            der_bytes = base64.b64decode(auth_b64)
            auth_key = serialization.load_der_private_key(der_bytes, password=None)
            keys.setdefault(user_id, {})["auth_priv"] = auth_key
            print(
                f"  Loaded auth_priv for {user_id}: RSA-{auth_key.public_key().key_size} bits (DER)"
            )
        except Exception as e:
            # Fallback: try PEM format
            pem_str = f"-----BEGIN RSA PRIVATE KEY-----\n{auth_b64}\n-----END RSA PRIVATE KEY-----"
            try:
                auth_key = serialization.load_pem_private_key(
                    pem_str.encode(), password=None
                )
                keys.setdefault(user_id, {})["auth_priv"] = auth_key
                print(
                    f"  Loaded auth_priv for {user_id} (PEM fallback): RSA-{auth_key.public_key().key_size} bits"
                )
            except Exception:
                print(f"  [WARN] Failed to load auth_priv for {user_id}: {e}")

        if license_b64:
            if isinstance(license_b64, bytes):
                license_b64 = license_b64.decode("utf-8", errors="replace")
            try:
                der_bytes = base64.b64decode(license_b64)
                license_key = serialization.load_der_private_key(
                    der_bytes, password=None
                )
                keys.setdefault(user_id, {})["license_priv"] = license_key
                print(
                    f"  Loaded license_priv for {user_id}: RSA-{license_key.public_key().key_size} bits (DER)"
                )
            except Exception as e:
                pem_str = f"-----BEGIN RSA PRIVATE KEY-----\n{license_b64}\n-----END RSA PRIVATE KEY-----"
                try:
                    license_key = serialization.load_pem_private_key(
                        pem_str.encode(), password=None
                    )
                    keys.setdefault(user_id, {})["license_priv"] = license_key
                    print(
                        f"  Loaded license_priv for {user_id} (PEM fallback): RSA-{license_key.public_key().key_size} bits"
                    )
                except Exception:
                    print(f"  [WARN] Failed to load license_priv for {user_id}: {e}")

    conn.close()
    return keys


def try_rsa_decrypt(encrypted_key_b64: str, private_key, label: str):
    """Try RSA-decrypting the content key with a given private key."""
    encrypted_bytes = base64.b64decode(encrypted_key_b64)

    results = []

    # Try PKCS1v15 (standard ADEPT padding)
    try:
        decrypted = private_key.decrypt(encrypted_bytes, asym_padding.PKCS1v15())
        results.append(("PKCS1v15", decrypted))
    except Exception as e:
        results.append(("PKCS1v15", str(e)))

    # Try OAEP with SHA-1 (less common but possible)
    try:
        decrypted = private_key.decrypt(
            encrypted_bytes,
            asym_padding.OAEP(
                mgf=asym_padding.MGF1(algorithm=hashes.SHA1()),
                algorithm=hashes.SHA1(),
                label=None,
            ),
        )
        results.append(("OAEP-SHA1", decrypted))
    except Exception as e:
        results.append(("OAEP-SHA1", str(e)))

    # Try OAEP with SHA-256
    try:
        decrypted = private_key.decrypt(
            encrypted_bytes,
            asym_padding.OAEP(
                mgf=asym_padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None,
            ),
        )
        results.append(("OAEP-SHA256", decrypted))
    except Exception as e:
        results.append(("OAEP-SHA256", str(e)))

    return results


def try_aes_decrypt_file(encrypted_data: bytes, content_key: bytes, label: str):
    """Try AES-CBC decrypting a file with the given key and various IV assumptions."""
    results = []

    if len(encrypted_data) < 16:
        results.append((label, f"Data too short ({len(encrypted_data)} bytes) for AES"))
        return results

    # Assumption A: IV is first 16 bytes of encrypted data
    try:
        iv_a = encrypted_data[:16]
        ciphertext_a = encrypted_data[16:]
        cipher = AES.new(content_key, AES.MODE_CBC, iv=iv_a)
        plaintext_a = cipher.decrypt(ciphertext_a)
        # Remove PKCS#7 padding
        pad_len = plaintext_a[-1]
        if 1 <= pad_len <= 16 and all(b == pad_len for b in plaintext_a[-pad_len:]):
            plaintext_a = plaintext_a[:-pad_len]
            results.append(("AES-CBC (IV=first16, unpadded)", plaintext_a))
        else:
            results.append(("AES-CBC (IV=first16, no pad removal)", plaintext_a[:80]))
    except Exception as e:
        results.append(("AES-CBC (IV=first16)", str(e)))

    # Assumption B: No IV prepended; IV is zero bytes
    try:
        iv_b = b"\x00" * 16
        ciphertext_b = encrypted_data
        cipher = AES.new(content_key, AES.MODE_CBC, iv=iv_b)
        plaintext_b = cipher.decrypt(ciphertext_b)
        pad_len = plaintext_b[-1]
        if 1 <= pad_len <= 16 and all(b == pad_len for b in plaintext_b[-pad_len:]):
            plaintext_b = plaintext_b[:-pad_len]
            results.append(("AES-CBC (IV=zeros, unpadded)", plaintext_b[:80]))
    except Exception as e:
        results.append(("AES-CBC (IV=zeros)", str(e)))

    # Assumption C: IV is all zeros and data has no leading block stripped
    try:
        iv_c = b"\x00" * 16
        cipher = AES.new(content_key, AES.MODE_CBC, iv=iv_c)
        plaintext_c = cipher.decrypt(encrypted_data)
        results.append(("AES-CBC (IV=zeros, raw)", plaintext_c[:80]))
    except Exception as e:
        results.append(("AES-CBC (IV=zeros)", str(e)))

    return results


def try_zlib_before_aes():
    """Check if encrypted files are zlib-compressed before AES encryption."""
    print("\n=== Testing zlib compression hypothesis ===")
    with zipfile.ZipFile(ENCRYPTED_EPUB) as zf:
        for name in [
            "OEBPS/toc.ncx",
            "OEBPS/isbn-9780197831229-front-matter-part-2.xhtml",
        ]:
            data = zf.read(name)
            try:
                import zlib

                decompressed = zlib.decompress(data, -zlib.MAX_WBITS)
                print(
                    f"  {name}: SUCCESSFUL zlib decompress -> {len(decompressed)} bytes"
                )
                return True
            except Exception:
                pass

    print("  No encrypted file is directly zlib-compressible.")
    return False


def main():
    print("=" * 70)
    print("ADEPT SPIKE PROBE")
    print("=" * 70)

    # --- Step 1: Parse rights.xml from the EPUB ---
    print("\n--- Step 1: Parsing META-INF/rights.xml ---")
    rights_root = parse_epub_xml(str(ENCRYPTED_EPUB), "META-INF/rights.xml")

    # Use iter() because elements are nested inside <licenseToken>
    user_id_elem = None
    resource_id_elem = None
    for elem in rights_root.iter():
        tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
        if tag == "user" and user_id_elem is None:
            user_id_elem = elem
        elif tag == "resource" and resource_id_elem is None:
            resource_id_elem = elem

    encrypted_key_b64 = None
    for elem in rights_root.iter():
        tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
        if tag == "encryptedKey" and elem.get("keyInfo") == "user":
            encrypted_key_b64 = "".join(elem.itertext()).strip()
            break

    user_id = user_id_elem.text if user_id_elem is not None else "NOT FOUND"
    resource_id = resource_id_elem.text if resource_id_elem is not None else "NOT FOUND"

    print(f"  User ID: {user_id}")
    print(f"  Resource ID: {resource_id}")
    if encrypted_key_b64:
        truncated = (
            "..." + encrypted_key_b64[-40:]
            if len(encrypted_key_b64) > 80
            else encrypted_key_b64
        )
        print(f"  Encrypted key (b64, first 40 chars): {truncated}")

    # --- Step 2: Load private keys from ADL DB ---
    print("\n--- Step 2: Loading private keys from ~/.adl/adl.db ---")
    key_map = load_private_keys(str(ADL_DB))
    for uid, kdict in key_map.items():
        for ktype, key in kdict.items():
            pub = key.public_key()
            print(f"  {uid} / {ktype}: RSA-{pub.key_size} bits")

    # --- Step 3: Try decrypting the content key with each key ---
    print("\n--- Step 3: Decrypting AES content key from rights.xml ---")

    if not encrypted_key_b64:
        print("  FATAL: Could not find <encryptedKey> in rights.xml!")
        sys.exit(1)

    for uid, kdict in key_map.items():
        for ktype, priv_key in kdict.items():
            label = f"{uid}/{ktype}"
            print(f"\n  Trying {label}...")
            results = try_rsa_decrypt(encrypted_key_b64, priv_key, label)
            for mode, result in results:
                if isinstance(result, bytes):
                    # Valid decryption!
                    content_key = result[:16]  # AES-128 key is first 16 bytes
                    print(f"    [{mode}] SUCCESS! Decrypted {len(result)} bytes")
                    print(f"    Content key (hex): {content_key.hex()}")

                    # Now test file decryption on a known binary and text file
                    print("\n    Testing AES-CBC file decryption with this key...")
                    with zipfile.ZipFile(ENCRYPTED_EPUB) as zf:
                        enc_data = zf.read(
                            "OEBPS/media/isbn-9780197831229-book-part-2-graphic-004.gif"
                        )

                    print(f"    Encrypted GIF size: {len(enc_data)} bytes")

                    # Try different IV assumptions
                    file_results = try_aes_decrypt_file(
                        enc_data, content_key, "GIF test"
                    )
                    for mode, result in file_results:
                        if isinstance(result, bytes):
                            if len(result) > 0 and not all(b == 0 for b in result[:16]):
                                # Check for valid GIF or JPEG header
                                if result[:4] in (b"GIF8", b"\xff\xd8\xff"):
                                    print(
                                        f"      [{mode}] VALID FILE HEADER FOUND: {result[:8]}"
                                    )
                                    # Save the decrypted file for manual inspection
                                    out_path = f"/tmp/decrypted_test_{mode.replace(' ', '_')}.gif"
                                    with open(out_path, "wb") as f:
                                        f.write(result)
                                    print(f"      Saved to {out_path}")
                                else:
                                    preview = result[:20].hex()
                                    printable = "".join(
                                        chr(b) if 32 <= b < 127 else "."
                                        for b in result[:40]
                                    )
                                    print(
                                        f"      [{mode}] output preview ({len(result)} bytes): {preview} ... '{printable}'"
                                    )

            # Also try with the full decrypted RSA output (not just first 16 bytes)
            try:
                decrypted_full = priv_key.decrypt(
                    base64.b64decode(encrypted_key_b64),
                    asym_padding.PKCS1v15(),
                )
                if len(decrypted_full) >= 16:
                    # The full decrypted content might be the AES key + IV, or just the AES key
                    print(
                        f"    Full RSA decryption ({len(decrypted_full)} bytes): {decrypted_full.hex()[:40]}..."
                    )

            except Exception:
                pass  # Already tested above

    # --- Step 4: Test zlib hypothesis ---
    try_zlib_before_aes()

    # --- Step 5: Compare ResourceSize vs encrypted file sizes ---
    print("\n--- Step 5: ResourceSize analysis (encryption.xml) ---")
    enc_xml = parse_epub_xml(str(ENCRYPTED_EPUB), "META-INF/encryption.xml")
    with zipfile.ZipFile(ENCRYPTED_EPUB) as zf:
        for ed in list(enc_xml)[:10]:
            uri_elem = ed.find(
                f"{{{NS_XMLENC}}}CipherData/{{{NS_XMLENC}}}CipherReference"
            )
            res_size_elem = ed.find(
                f"{{{NS_XMLENC}}}EncryptionProperties/{{{NS_XMLENC}}}ResourceSize"
            )
            if uri_elem is not None and res_size_elem is not None:
                uri = uri_elem.get("URI", "")
                resource_size = int(res_size_elem.text)
                try:
                    actual_size = zf.getinfo(uri).file_size
                    ratio = actual_size / resource_size if resource_size > 0 else 0
                    print(
                        f"  {uri}: ResourceSize={resource_size}, encrypted={actual_size}, ratio={ratio:.3f}"
                    )
                except KeyError:
                    pass

    # --- Step 6: Check the decrypted EPUB for compression patterns ---
    print("\n--- Step 6: Decrypted EPUB file sizes (for comparison) ---")
    with zipfile.ZipFile(DECRYPTED_EPUB) as zf:
        for name in [
            "OEBPS/toc.ncx",
            "OEBPS/isbn-9780197831229-front-matter-part-2.xhtml",
        ]:
            if name in zf.namelist():
                info = zf.getinfo(name)
                data = zf.read(name)
                print(
                    f"  {name}: compress_type={info.compress_type}, decompressed_size={len(data)}"
                )

    print("\n" + "=" * 70)
    print("SPIKE PROBE COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    main()
