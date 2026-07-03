# ADEPT EPUB Decryption — Structured Tickets

**Date:** 2026-07-03  
**Source plan:** `plan.md`

---

## Ticket 1: CLI entry point `adl-decode` with argument parsing

**Status:** ✅ Completed (commit: initial scaffold)  
**Plan section:** Phase 4 — Write the output EPUB

### Description
Create a callable program `uv run adl-decode` that accepts:
- A list of EPUB files (positional arguments)
- `--adl-database` flag (default: `~/.adl/adl.db`)
- `--output-directory` flag (default: `./epub`)

### Acceptance Criteria
- Running `uv run adl-decode` with no arguments prints help and returns exit code 1
- Running `uv run adl-decode --help` shows usage information
- The argument parser correctly parses `--adl-database`, `--output-directory`, and positional EPUB file paths
- The output directory is created if it does not exist

### Files Changed
- `src/adl/adept.py` — `build_parser()`, `main()`

---

## Ticket 2: Extract and parse `rights.xml` from an EPUB

**Status:** ✅ Completed (commit: extract rights and encryption XML)  
**Plan section:** Phase 2 — Decrypt the content key from rights.xml

### Description
Extract and parse `META-INF/rights.xml` from an ADEPT-protected EPUB. The rights XML contains:
- `<user>` — user ID matching `users.user_id` in the ADL DB
- `<resource>` — book resource UUID
- `<encryptedKey keyInfo="user">` — base64-encoded RSA ciphertext containing the AES content key

### Acceptance Criteria
- `extract_rights_and_encryption()` returns a tuple of `(rights_data, encryption_map)`
- `rights_data` is a dict with `{user_id, resource_id, encrypted_key_b64}` or `None` if rights.xml is missing
- XML namespace handling works correctly (elements nested inside `<licenseToken>`)

### Files Changed
- `src/adl/adept.py` — `extract_rights_and_encryption()`

---

## Ticket 3: Load RSA private key from ADL database

**Status:** ✅ Completed (commit: load private key from ADL DB)  
**Plan section:** Phase 1 — Extract private key from ADL DB

### Description
Load the RSA private key from `~/.adl/adl.db` for a given ADEPT user. Key columns (`auth_priv`, `license_priv`) contain **base64-encoded DER blobs** (not PEM).

### Acceptance Criteria
- `load_private_key(db_path, user_id)` queries the `users` table for the matching `user_id`
- Tries `license_priv` first (produces clean 16-byte AES key), falls back to `auth_priv`
- Returns an `rsa.RSAPrivateKey` object from the cryptography library
- Raises `ValueError` if no matching user or usable key is found

### Files Changed
- `src/adl/adept.py` — `load_private_key()`

---

## Ticket 4: Decrypt the AES content key from rights.xml

**Status:** ✅ Completed (commit: decrypt content key with RSA-PKCS1v15)  
**Plan section:** Phase 2 — Decrypt the content key from rights.xml

### Description
RSA-decrypt the AES-128 content key stored in `rights.xml` using the private key from Ticket 3.

### Acceptance Criteria
- `decrypt_content_key(encrypted_key_bytes, private_key)` returns a 16-byte AES-128 key
- Uses PKCS#1 v1.5 padding (confirmed by spike probe; OAEP variants fail)
- Accepts base64-decoded RSA ciphertext (128 bytes for 1024-bit RSA)

### Files Changed
- `src/adl/adept.py` — `decrypt_content_key()`

---

## Ticket 5: Decrypt a single file (AES-CBC + PKCS#7 unpad + raw deflate)

**Status:** ✅ Completed (commit: add decrypt_file for AES-CBC + PKCS#7 unpad + raw deflate)  
**Plan section:** Phase 3 — Parse encryption.xml and decrypt files

### Description
Decrypt a single file from an ADEPT EPUB. The decryption pipeline (verified by spike probe):
1. AES-128-CBC decrypt (IV = first 16 bytes of encrypted_data)
2. PKCS#7 unpadding
3. Raw deflate decompression (`wbits=-zlib.MAX_WBITS`, no zlib header)

### Acceptance Criteria
- `decrypt_file(encrypted_data, content_key)` returns the original plaintext bytes
- GIF decryption produces byte-for-byte match with reference EPUB (15313 bytes)
- XHTML decryption produces valid XML content
- Round-trip test: encrypt → decrypt returns original data

### Files Changed
- `src/adl/adept.py` — `decrypt_file()`
- `tests/test_adept_decrypt_file.py` — new test file (6 tests)

---

## Ticket 6: Parse `encryption.xml` and build encrypted file mapping

**Status:** ✅ Completed (integrated into Ticket 2)  
**Plan section:** Phase 3 — Parse encryption.xml and decrypt files

### Description
Extract `META-INF/encryption.xml` from the EPUB and build a mapping of encrypted file URIs to their resource UUIDs. All 83 `<EncryptedData>` entries in the test book reference a single resource UUID (one content key for all files).

### Acceptance Criteria
- `extract_rights_and_encryption()` parses `META-INF/encryption.xml` when present
- Returns `encryption_map`: dict mapping file URIs to resource UUIDs
- Handles `<CipherReference URI="...">` and `<resource>` elements correctly

### Files Changed
- `src/adl/adept.py` — extended `extract_rights_and_encryption()` (encryption.xml parsing)

---

## Ticket 7: Full EPUB decryption pipeline — write decrypted output

**Status:** ✅ Completed (commit: add decrypt_epub for full EPUB decryption pipeline)  
**Plan section:** Phase 3 & 4 — Decrypt files + Write the output EPUB

### Description
Full EPUB decryption: extract rights.xml and encryption.xml, load RSA key, decrypt AES content key, then for each file in encryption.xml — decrypt and write to output EPUB.

### Acceptance Criteria
- `decrypt_epub(encrypted_epub_path, output_epub_path, adl_db_path)` produces a valid `.epub` file
- `mimetype` entry is stored uncompressed (`ZIP_STORED`) per EPUB spec
- All other entries use `ZIP_DEFLATED` compression
- GIF file in output matches reference decrypted EPUB byte-for-byte
- All 83 encrypted files are present and decrypted in the output

### Files Changed
- `src/adl/adept.py` — `decrypt_epub()`
- `tests/test_adept_pipeline.py` — new test file (6 tests)

---

## Ticket 8: Multi-file batch decryption in CLI

**Status:** ✅ Completed (commit: integrate decrypt_epub into CLI main)  
**Plan section:** Phase 4 — Write the output EPUB

### Description
Integrate `decrypt_epub()` into the CLI so that `uv run adl-decode` decrypts all provided EPUB files.

### Acceptance Criteria
- `main()` iterates over all positional EPUB arguments and calls `decrypt_epub()` for each
- Output filename strips `-encrypted` suffix (e.g., `book-encrypted.epub` → `book.epub`)
- CLI accepts `--adl-database` (default: `~/.adl/adl.db`) and `--output-directory` (default: `./epub`)
- Running with no files shows help and returns exit code 1

### Files Changed
- `src/adl/adept.py` — updated `main()`
- `tests/test_adept_cli.py` — new test file (5 tests)

---

## Summary of Implementation

| Ticket   | Function                            | Tests   | Commit                                                    |
|----------|-------------------------------------|---------|-----------------------------------------------------------|
| 1        | `build_parser()`, `main()` scaffold | —       | initial CLI scaffold                                      |
| 2        | `extract_rights_and_encryption()`   | —       | extract rights and encryption XML                         |
| 3        | `load_private_key()`                | —       | load private key from ADL DB                              |
| 4        | `decrypt_content_key()`             | —       | decrypt content key with RSA-PKCS1v15                     |
| 5        | `decrypt_file()`                    | 6 tests | add decrypt_file for AES-CBC + PKCS#7 unpad + raw deflate |
| 6        | (integrated into Ticket 2)          | —       | (same commit as Ticket 2)                                 |
| 7        | `decrypt_epub()`                    | 6 tests | add decrypt_epub for full EPUB decryption pipeline        |
| 8        | `main()` integration                | 5 tests | integrate decrypt_epub into CLI main                      |

**Total: 17 new tests, all passing.**
