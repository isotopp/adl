# ADEPT EPUB Decryption Integration Plan

**Date:** 2026-07-03

## Goal

Decrypt an Adobe ADEPT-protected EPUB (`Making a Career in Dictatorship-encrypted.epub`) using private key material from `~/.adl/adl.db` and the license/encryption XML files embedded in the EPUB, producing a plaintext `.epub`.

---

## What We Have

| Item | Location | Purpose |
|------|----------|---------|
| Encrypted EPUB | `/Users/kris/Source/adl/Making a Career in Dictatorship-encrypted.epub` | Input: ADEPT-protected ZIP with encrypted content files |
| ADL authorization DB | `~/.adl/adl.db` | Account/device private key material (`auth_priv`, `license_priv`) for the ADEPT identity |
| Encrypted EPUB (pre-existing) | `/Users/kris/Source/adl/Making a Career in Dictatorship-decrypted.epub` | Reference output; already decrypted by some other means |

### ADL DB Schema

```sql
CREATE TABLE users (
    user_id text PRIMARY KEY,       -- e.g. urn:uuid:0d776b19-...
    sign_id text,                   -- "anonymous" or email
    sign_method text,               -- how the user was identified
    auth_pub text,                  -- RSA public key (PEM)
    auth_priv text,                 -- RSA private key (PEM)  <-- KEY MATERIAL
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

### Rights XML (`META-INF/rights.xml` inside EPUB)

Contains a `<licenseToken>` with:

- `<user>urn:uuid:0d776b19-d03e-4e9c-936d-3959f6f08f19</user>` — matches `users.user_id` in ADL DB
- `<resource>urn:uuid:77187695-4844-42fb-baca-d0fc0d10dd3d</resource>` — book resource ID
- `<encryptedKey keyInfo="user">WYsceFj3rl...</encryptedKey>` — base64-encoded content encryption key, encrypted with the user's account RSA private key
- `<device>urn:uuid:6fd8273e-6977-4fd9-b49e-bcf45a96344e</device>` — matches `devices.device_id` in ADL DB

### Encryption XML (`META-INF/encryption.xml` inside EPUB)

Lists 83 `<EncryptedData>` entries. Each has:

```xml
<EncryptedData>
    <EncryptionMethod Algorithm="http://www.w3.org/2001/04/xmlenc#aes128-cbc"/>
    <KeyInfo><resource xmlns="http://ns.adobe.com/adept">urn:uuid:77187695-4844-42fb-baca-d0fc0d10dd3d</resource></KeyInfo>
    <CipherData><CipherReference URI="OEBPS/media/isbn-9780197831229-book-part-2-graphic-004.gif"/></CipherData>
</EncryptedData>
```

All entries reference the same resource UUID, meaning one content key decrypts all 83 files.

---

## How Adobe ADEPT DRM Works (vs Kobo)

### Kobo DRM (what `obok` currently handles)

1. Derive a user key from MAC address + device serial via SHA-256 hashing chain
2. Per-file page keys stored in the Kobo DB (`content_keys`) table as base64-encoded blobs
3. Two-stage ECB decryption: first decrypt the page key with the derived user key, then decrypt file content with that page key (ECB mode)

### Adobe ADEPT DRM (what we need to support)

1. **One shared content key per book/license** — encrypted once with RSA
2. The `<encryptedKey>` in `rights.xml` is the AES-128 content key, RSA-encrypted using the user's account private key (`auth_priv` from ADL DB)
3. Files are encrypted with AES-CBC (as specified by the `EncryptionMethod` algorithm URI in `encryption.xml`)
4. The IV for each file is stored as the first 16 bytes of the encrypted content

**The two schemes are fundamentally different.** Obok's key derivation, page-key lookup, and ECB-mode decryption do not apply to ADEPT EPUBs.

---

## Plan

### Phase 1: Extract private key from ADL DB (no obok code reuse)

1. Open `~/.adl/adl.db`
2. Look up the user whose `user_id` matches `<user>` in the EPUB's `rights.xml`:
   ```sql
   SELECT license_priv, auth_priv FROM users WHERE user_id = 'urn:uuid:0d776b19-d03e-4e9c-936d-3959f6f08f19';
   ```
3. The `auth_priv` or `license_priv` column contains the RSA private key in PEM format (base64-encoded text).
4. Load it via `cryptography.hazmat.primitives.serialization.load_pem_private_key()` — **do not use ctypes/libcrypto**.

**No obok code is reused here.** This is a simple SQLite query + cryptography library call.

### Phase 2: Decrypt the content key from rights.xml (no obok code reuse)

1. Extract `META-INF/rights.xml` from the EPUB
2. Parse the XML, handling ADEPT namespaces (`http://ns.adobe.com/adept`)
3. Find `<encryptedKey>` element with `keyInfo="user"` — this is base64-encoded RSA-encrypted AES key
4. Decode base64 to get ciphertext (128 bytes = 1024-bit RSA ciphertext)
5. Decrypt using the private key from Phase 1:
   ```python
   content_key = private_key.decrypt(
       encrypted_key_bytes,
       padding.PKCS1v15()
   )
   ```
6. The result is a 16-byte AES-128 key.

**No obok code is reused here.** This is standard ADEPT protocol logic using the `cryptography` library (already in the project dependency chain).

### Phase 3: Parse encryption.xml and decrypt files

1. Extract `META-INF/encryption.xml` from the EPUB
2. Build a mapping: `{ "OEBPS/media/isbn-....gif": "urn:uuid:77187695-..." }` — maps each encrypted file URI to its resource UUID
3. Open the EPUB as a ZIP archive (same pattern as `KoboBook.encryptedfiles` in obok)
4. For each entry in encryption.xml:
   - Read the encrypted bytes from the EPUB
   - The first 16 bytes are the IV; the rest is ciphertext
   - Decrypt with AES-CBC using the content key from Phase 2:
     ```python
     iv = contents[:16]
     ciphertext = contents[16:]
     plaintext = AES.new(content_key, AES.MODE_CBC, iv).decrypt(ciphertext)
     ```
5. For non-encrypted files (not in encryption.xml), pass through as-is
6. Write the unmodified `mimetype` file first (uncompressed, per EPUB spec)
7. Write all other files to a new ZIP/EPUB

**Partial obok code reuse:** The ZIP handling pattern from `decrypt_book()` can serve as a reference structure — iterating over `namelist()`, reading each entry conditionally transforming it, and writing to output. The actual crypto differs (AES-CBC vs AES-ECB two-stage).

### Phase 4: Write the output EPUB

1. Create a new ZIP file
2. Write `mimetype` as first entry, uncompressed (`ZIP_STORED`) — this is required by the EPUB spec for valid EPUBs
3. Write all other entries (encrypted files now decrypted + unencrypted pass-through files) with `ZIP_DEFLATED` compression

---

## What from obok Can Be Reused

| Obok Component                              | Usable?            | Notes                                                                                                                                              |
|---------------------------------------------|--------------------|----------------------------------------------------------------------------------------------------------------------------------------------------|
| `crypto.unpad()` (`src/adl/obok/crypto.py`) | **Yes**            | PKCS#7 unpadding utility. Though AES-CBC decryption with proper padding from the server shouldn't need it, it's a safe helper to have available.   |
| `KoboBook` / `KoboLibrary` classes          | **No**             | These are tightly coupled to Kobo DB schema (`content`, `content_keys` tables) and MAC-based key derivation. Not applicable to ADEPT.              |
| ZIP iteration pattern in `decrypt_book()`   | **Reference only** | The structure of iterating EPUB entries, conditionally decrypting, and writing output is similar but the crypto ops differ entirely.               |
| CLI infrastructure (`src/adl/obok/cli.py`)  | **No**             | Built around Kobo library discovery (device paths, desktop directories). ADEPT decryption needs a different input model (EPUB path + ADL DB path). |

### Recommended approach

Create a separate module `src/adl/adept.py` rather than modifying obok:

```
src/adl/
  adept.py          # New: ADEPT EPUB decryption (rights.xml + encryption.xml + ADL private key)
  obok/
    __init__.py     # Unchanged
    models.py       # Unchanged — Kobo-specific, do not modify
    crypto.py       # Can optionally export unpad() at package level if needed
    cli.py          # Unchanged
```

This keeps the two DRM removal paths separate and maintainable.

---

## Architecture of `adept.py`

```python
"""Adobe ADEPT EPUB decryption using ADL authorization database keys."""

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from Cryptodome.Cipher import AES


def load_adept_private_key(db_path: str, user_id: str) -> PrivateKey:
    """Load the RSA private key from ~/.adl/adl.db for a given ADEPT user."""
    # Query auth_priv or license_priv from users table
    ...


def extract_rights_and_encryption(encrypted_epub_path: str):
    """Extract and parse META-INF/rights.xml and META-INF/encryption.xml from an EPUB.
    
    Returns:
        rights_data: dict with user_id, resource_id, encrypted_key (bytes)
        encryption_map: { "OEBPS/path/to/file": "resource-uuid" }
    ...


def decrypt_content_key(encrypted_key_bytes: bytes, private_key: PrivateKey) -> bytes:
    """RSA-decrypt the AES content key from rights.xml using the ADEPT account private key."""
    # PKCS1v15 unpad + RSA decrypt
    ...


def decrypt_epub(encrypted_epub_path: str, output_path: str, db_path: str):
    """Main entry point. Decrypts an ADEPT-protected EPUB using ADL DB keys.
    
    1. Extract rights.xml and encryption.xml from the EPUB
    2. Match <user> in rights.xml to a row in ~/.adl/adl.db
    3. Load RSA private key from auth_priv column
    4. Decrypt the AES content key with RSA
    5. For each file listed in encryption.xml, decrypt with AES-CBC using the content key
    6. Write decrypted EPUB to output_path
    """
    ...
```

---

## Dependencies

The project already depends on:

- `cryptography` — for loading PEM private keys and PKCS1v15 RSA decryption
- `pycryptodomex` (`Cryptodome.Cipher.AES`) — already used by obok, can be reused here for AES-CBC

No new dependencies needed.

---

## Verification Steps

1. **Compare with existing decrypted file:** After implementing the decryption pipeline, compare the output against `Making a Career in Dictatorship-decrypted.epub` using checksums or diff on extracted content to validate correctness.
2. **Verify mimetype is stored uncompressed** — EPUB readers require this.
3. **Test with another ADEPT-encrypted book** from ADL if available, to confirm the solution generalizes beyond a single test case.

---

## Risk Areas

1. **Which private key column?** `auth_priv` vs `license_priv` — both are RSA private keys in the ADL DB. The correct one depends on which key was used to encrypt the content key in rights.xml. In practice, we should try `auth_priv` first, then fall back to `license_priv`.
2. **PKCS1v15 vs OAEP padding** — ADEPT standard uses PKCS#1 v1.5 padding for RSA decryption. If that fails with one private key, try the other; if both fail, we may need to investigate alternative padding modes.
3. **IV handling** — Some ADEPT implementations store the IV separately from the ciphertext (e.g., in a `<CipherData>` element). The encryption.xml structure here appears to embed the full encrypted content per file reference, with IV prepended as the first 16 bytes — but this should be verified empirically.
4. **Multiple resource keys** — If different files use different resource UUIDs (different content keys), we'd need to handle multiple `<encryptedKey>` entries in rights.xml or derive secondary keys from the primary one. For this book, all files share one resource UUID.
