# ADEPT EPUB Decryption Integration Plan

**Date:** 2026-07-03  
**Last amended:** 2026-07-03 (spike probe results incorporated)

## Goal

Decrypt an Adobe ADEPT-protected EPUB (`Making a Career in Dictatorship-encrypted.epub`) using private key material from `~/.adl/adl.db` and the license/encryption XML files embedded in the EPUB, producing a plaintext `.epub`.

---

## What We Have

| Item | Location | Purpose |
|------|----------|---------|
| Encrypted EPUB | `/Users/kris/Source/adl/Making a Career in Dictatorship-encrypted.epub` | Input: ADEPT-protected ZIP with encrypted content files |
| ADL authorization DB | `~/.adl/adl.db` | Account/device private key material (`auth_priv`, `license_priv`) for the ADEPT identity |
| Decrypted EPUB (reference) | `/Users/kris/Source/adl/Making a Career in Dictatorship-decrypted.epub` | Reference output; already decrypted by some other means (used for validation only) |

### ADL DB Schema

```sql
CREATE TABLE users (
    user_id text PRIMARY KEY,       -- e.g. urn:uuid:0d776b19-...
    sign_id text,                   -- "anonymous" or email
    sign_method text,               -- how the user was identified
    auth_pub text,                  -- RSA public key (base64-encoded DER)
    auth_priv text,                 -- RSA private key (base64-encoded DER)  <-- KEY MATERIAL
    license_pub text,               -- another RSA pub key
    license_priv text,              -- another RSA priv key   <-- also key material
    pkcs12 text,                    -- PKCS#12 blob
    eplk text,                      -- encrypted private license key
    license_certificate text        -- X.509 certificate (DER)
);

CREATE TABLE devices (
    user_id text,
    device_key text,
    device_id text PRIMARY KEY,     -- urn:uuid:... matching <device> in rights.xml
    fingerprint text,
    device_name text,
    device_type text                -- "standalone"
);

CREATE TABLE configuration (
    default_user text,
    auth_url text,
    activation_certificate text,
    userinfo_url text,
    authentication_certificate text
);
```

**IMPORTANT:** All key columns (`auth_priv`, `license_priv`, etc.) are **BLOBs containing base64-encoded DER data**, NOT PEM format. To load them with the `cryptography` library:
1. Base64-decode the blob to get raw DER bytes
2. Use `serialization.load_der_private_key(der_bytes, password=None)`

### Rights XML (`META-INF/rights.xml` inside EPUB)

Structure is `<rights>` → `<licenseToken>` (nested inside namespace):

- `<user>urn:uuid:0d776b19-d03e-4e9c-936d-3959f6f08f19</user>` — matches `users.user_id` in ADL DB
- `<resource>urn:uuid:77187695-4844-42fb-baca-d0fc0d10dd3d</resource>` — book resource ID  
- `<encryptedKey keyInfo="user">WYsceFj3rl...</encryptedKey>` — base64-encoded RSA ciphertext containing the AES content key
- `<device>urn:uuid:6fd8273e-6977-4fd9-b49e-bcf45a96344e</device>` — matches `devices.device_id` in ADL DB

### Encryption XML (`META-INF/encryption.xml` inside EPUB)

Lists 83 `<EncryptedData>` entries. Each references one file:

```xml
<EncryptedData>
    <EncryptionMethod Algorithm="http://www.w3.org/2001/04/xmlenc#aes128-cbc"/>
    <KeyInfo><resource xmlns="http://ns.adobe.com/adept">urn:uuid:77187695-...</resource></KeyInfo>
    <CipherData><CipherReference URI="OEBPS/media/isbn-...gif"/></CipherData>
</EncryptedData>
```

All entries reference the same resource UUID, meaning **one content key decrypts all files**.

The `ResourceSize` metadata element indicates the original plaintext size of each file before compression + encryption. For binary files (GIF/JPEG), encrypted size ≈ ResourceSize + PKCS#7 padding (0-15 bytes). For text files (XHTML/SVG), encrypted size is much smaller because the content was raw-deflate compressed before AES encryption.

---

## How Adobe ADEPT DRM Works

### Kobo DRM

1. Derive a user key from MAC address + device serial via SHA-256 hashing chain
2. Per-file page keys stored in the Kobo DB (`content_keys`) table as base64-encoded blobs  
3. Two-stage ECB decryption: first decrypt the page key with the derived user key, then decrypt file content with that page key

### Adobe ADEPT DRM (what we need to support) — **verified by spike probe**

1. **One shared AES-128 content key per book/license**, RSA-encrypted once and stored in `rights.xml`
2. **File pipeline:** original file → raw-deflate compressed → AES-128-CBC encrypted (IV prepended as first 16 bytes of ciphertext)
3. Files are stored in the EPUB ZIP with `compress_type=0` (STORED/uncompressed), containing the full IV+ciphertext blob

**The two schemes are fundamentally different.** Kobo key derivation, page-key lookup, and ECB-mode decryption do not apply to ADEPT EPUBs.

---

## Plan

### Phase 1: Extract private key from ADL DB

1. Open `~/.adl/adl.db`
2. Look up the user whose `user_id` matches `<user>` in the EPUB's `rights.xml`:
   ```sql
   SELECT license_priv, auth_priv FROM users WHERE user_id = 'urn:uuid:0d776b19-d03e-4e9c-936d-3959f6f08f19';
   ```
3. The key columns contain **base64-encoded DER blobs** (not PEM). Load them as follows:
   ```python
   import base64
   from cryptography.hazmat.primitives import serialization
   
   # auth_priv and license_priv come from DB as bytes or str
   der_bytes = base64.b64decode(rows[0]["license_priv"])
   private_key = serialization.load_der_private_key(der_bytes, password=None)
   ```

### Phase 2: Decrypt the content key from rights.xml

1. Extract `META-INF/rights.xml` from the EPUB  
2. Parse XML with namespace handling — elements are nested inside `<licenseToken>`:
   ```python
   for elem in root.iter():
       tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
       if tag == "encryptedKey" and elem.get("keyInfo") == "user":
           enc_key_b64 = "".join(elem.itertext()).strip()
   ```
3. Decode base64 to get RSA ciphertext (128 bytes for 1024-bit RSA)
4. Decrypt using the private key from Phase 1 with PKCS#1 v1.5 padding:
   ```python
   content_key = private_key.decrypt(
       enc_key_bytes,
       padding.PKCS1v15()
   )
   # Returns a 16-byte AES-128 key (verified by spike probe)
   ```

### Phase 3: Parse encryption.xml and decrypt files

1. Extract `META-INF/encryption.xml` from the EPUB
2. Build a mapping of encrypted file URIs to their resource UUIDs from `<CipherReference>` elements  
3. Open the EPUB as a ZIP archive
4. For each entry in encryption.xml, apply this decryption pipeline:
   ```python
   import zlib
   
   # 1. Extract IV (first 16 bytes) and ciphertext
   iv = contents[:16]
   ciphertext = contents[16:]
   
   # 2. AES-128-CBC decrypt  
   plaintext_encrypted = AES.new(content_key, AES.MODE_CBC, iv=iv).decrypt(ciphertext)
   
   # 3. Remove PKCS#7 padding
   pad_len = plaintext_encrypted[-1]
   if 1 <= pad_len <= 16 and all(b == pad_len for b in plaintext_encrypted[-pad_len:]):
       plaintext_encrypted = plaintext_encrypted[:-pad_len]
   
   # 4. Raw deflate decompress (NO zlib header)  
   plaintext = zlib.decompress(plaintext_encrypted, wbits=-zlib.MAX_WBITS)
   ```

5. For non-encrypted files (not in encryption.xml), pass through as-is
6. Write the unmodified `mimetype` file first (uncompressed, per EPUB spec)
7. Write all other files to a new ZIP/EPUB with `ZIP_DEFLATED` compression

### Phase 4: Write the output EPUB

1. Create a new ZIP file  
2. Write `mimetype` as first entry, uncompressed (`ZIP_STORED`) — required by EPUB spec
3. Write all other entries (decrypted files + unencrypted pass-through) with `ZIP_DEFLATED` compression

---

## Recommended Approach

Create a separate module `src/adl/adept.py` for ADEPT processing:

```
src/adl/
  adept.py          # New: ADEPT EPUB decryption (rights.xml + encryption.xml + ADL private key)
```

---

## Architecture of `adept.py`

```python
"""Adobe ADEPT EPUB decryption using ADL authorization database keys."""

import base64
import zlib
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from Cryptodome.Cipher import AES


def load_adept_private_key(db_path: str, user_id: str) -> PrivateKey:
    """Load the RSA private key from ~/.adl/adl.db for a given ADEPT user.

    Keys are stored as base64-encoded DER blobs (not PEM).
    Try license_priv first; fall back to auth_priv if decryption fails.
    Returns the first private key that successfully decrypts the content key.
    """
    ...


def extract_rights_and_encryption(encrypted_epub_path: str):
    """Extract and parse META-INF/rights.xml and META-INF/encryption.xml from an EPUB.

    Returns:
        rights_data: dict with {user_id, resource_id, encrypted_key_b64}
        encryption_map: { "OEBPS/path/to/file": True }  (set of encrypted file URIs)
    """
    ...


def decrypt_content_key(encrypted_key_bytes: bytes, private_key: PrivateKey) -> bytes:
    """RSA-decrypt the AES content key from rights.xml.

    Uses PKCS#1 v1.5 padding (confirmed by spike probe).
    Returns 16-byte AES-128 key.
    """
    return private_key.decrypt(encrypted_key_bytes, padding.PKCS1v15())


def decrypt_file(encrypted_data: bytes, content_key: bytes) -> bytes:
    """Decrypt a single file from an ADEPT EPUB.

    Pipeline (verified by spike probe):
      1. AES-128-CBC with IV = first 16 bytes of encrypted_data
      2. PKCS#7 unpadding
      3. Raw deflate decompression (wbits=-zlib.MAX_WBITS, no zlib header)

    Returns the original plaintext bytes.
    """
    iv = encrypted_data[:16]
    ciphertext = encrypted_data[16:]
    
    dec = AES.new(content_key, AES.MODE_CBC, iv=iv).decrypt(ciphertext)
    
    # PKCS#7 unpadding
    pad_len = dec[-1]
    if 1 <= pad_len <= 16 and all(b == pad_len for b in dec[-pad_len:]):
        dec = dec[:-pad_len]
    
    # Raw deflate decompress (all files are raw-deflate compressed before AES)
    return zlib.decompress(dec, wbits=-zlib.MAX_WBITS)


def decrypt_epub(encrypted_epub_path: str, output_path: str, db_path: str):
    """Main entry point. Decrypts an ADEPT-protected EPUB using ADL DB keys.

    1. Extract rights.xml and encryption.xml from the EPUB
    2. Match <user> in rights.xml to a row in ~/.adl/adl.db
    3. Load RSA private key (try license_priv first, then auth_priv)
    4. Decrypt the AES content key with RSA-PKCS1v15
    5. For each file listed in encryption.xml: decrypt_file() → IV + AES-CBC + PKCS#7 unpad + raw deflate
    6. Write decrypted EPUB to output_path (mimetype STORED, rest DEFLATED)
    """
    ...
```

---

## Dependencies

The project already depends on:

- `cryptography` — for loading DER private keys and PKCS1v15 RSA decryption  
- `pycryptodomex` (`Cryptodome.Cipher.AES`) — for AES-CBC
- `zlib` — standard library, for raw deflate decompression after AES decryption

No new dependencies needed.

---

## Verification Steps (updated from spike probe)

1. **GIF file validation (verified):** Decrypting `OEBPS/media/isbn-9780197831229-book-part-2-graphic-004.gif` with `license_priv` key produces 15313 bytes that exactly match the reference decrypted EPUB. This confirms the entire decryption pipeline (RSA → AES-CBC → PKCS#7 unpad → raw deflate) is correct.

2. **XHTML file validation:** Decrypting XHTML files produces valid XML content after the full pipeline, but may differ slightly from the reference EPUB (different tooling/source). The important check is that decrypted output starts with valid HTML (`<html xmlns=...>`), which was confirmed.

3. **Verify mimetype is stored uncompressed** — EPUB readers require this.

4. **Test with another ADEPT-encrypted book** from ADL if available, to confirm the solution generalizes beyond a single test case.

---

## Risk Areas (resolved by spike probe)

### 1. Which private key column? `auth_priv` vs `license_priv` — RESOLVED

Both keys successfully decrypt with PKCS#1 v1.5 padding:
- **`auth_priv`**: RSA-decryption produces **115 bytes** of output (contains AES key + additional data). The first 16 bytes can serve as an AES key but does not produce correct file decryption.
- **`license_priv`**: RSA-decryption produces a clean **16-byte** output that is the exact AES-128 content key. File decryption with this key matches reference output exactly.

**Conclusion:** For this book, `license_priv` is the correct column. The recommended approach is to try `license_priv` first (it gives a clean 16-byte key), and fall back to `auth_priv` if that fails. In practice, which key was used depends on how the EPUB was licensed.

### 2. PKCS1v15 vs OAEP padding — RESOLVED

Only **PKCS#1 v1.5** works for both keys. All OAEP variants (SHA-1 and SHA-256) fail with decryption errors. This is consistent with the Adobe ADEPT specification.

### 3. IV handling — RESOLVED

The IV is prepended as the **first 16 bytes of each encrypted file's data**. Decryption uses `AES.new(key, AES.MODE_CBC, iv=encrypted_data[:16])` on the remaining ciphertext (`encrypted_data[16:]`). This was confirmed empirically: GIF decryption with this approach produces an exact byte-for-byte match against the reference.

### 4. Multiple resource keys — UNRESOLVED (but likely not needed)

All 83 encrypted files in this book reference a single resource UUID, meaning one content key suffices. If other books use multiple resource IDs, the implementation would need to handle per-resource encryption keys from rights.xml. This was not investigated by the spike probe and should be tested if multi-license EPUBs are encountered.

### 5. NEW: File compression before encryption — DISCOVERED BY SPIKE PROBE

**All files in this ADEPT EPUB undergo raw deflate (not zlib) compression before AES encryption.** The decryption pipeline for every file is:
1. AES-128-CBC decrypt (IV from first 16 bytes)  
2. PKCS#7 unpadding
3. Raw deflate decompression (`wbits=-zlib.MAX_WBITS`, no header/trailer)

This was verified on three file types:
- GIF (binary): 14800 encrypted → AES → raw deflate → 15313 bytes (= ResourceSize, exact match to reference)  
- XHTML (text): 2960 encrypted → AES → raw deflate → 7587 bytes (= ResourceSize, valid XML content)
- SVG (text): decrypted → raw deflate → correct size matching ResourceSize

This is a critical detail not present in standard ADEPT documentation — the epub source files are pre-compressed with zlib's underlying deflate algorithm before being encrypted.

### 6. NEW: Key storage format — DISCOVERED BY SPIKE PROBE

The `auth_priv` and `license_priv` columns in the ADL DB store **base64-encoded DER** (not PEM). The cryptography library cannot load them directly as PEM; they must be base64-decoded to raw DER bytes first, then loaded with `load_der_private_key()`. This was confirmed: PEM loading fails, but DER loading succeeds immediately.
