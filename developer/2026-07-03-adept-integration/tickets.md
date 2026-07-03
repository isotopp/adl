# ADEPT Integration — Structured Tickets

**Source:** `plan.md`  
**CLI contract:** `uv run adl-decode --adl-database ~/.adl/adl.db --output-directory ./epub book1.epub [book2.epub ...]`

---

## Ticket 1: CLI entry point `adl-decode` with argument parsing

**Goal:** A callable program `uv run adl-decode` that accepts encrypted EPUB file paths and optional flags.

### Test (RED)
- `adl-decode` is invokable via `uv run adl-decode --help` and prints usage.
- `adl-decode book.epub` exits 0 with no errors (no decryption yet — just argument parsing).
- `--adl-database` defaults to `~/.adl/adl.db`.
- `--output-directory` defaults to `./epub`.

### Implementation (GREEN)
- Add `[project.scripts]` entry `adl-decode = "adl.adept:main"` in `pyproject.toml`.
- Create `src/adl/adept.py` with a `main()` function that:
  - Uses `argparse` to parse positional EPUB file arguments.
  - Accepts optional `--adl-database` (default: `~/.adl/adl.db`).
  - Accepts optional `--output-directory` (default: `./epub`).
  - Creates the output directory if it does not exist.

### Acceptance criteria
- `uv run adl-decode --help` prints help text.
- `uv run adl-decode test.epub` returns exit code 0 without crashing.

---

## Ticket 2: Extract and parse `rights.xml` from an EPUB

**Goal:** Given a path to an encrypted EPUB, extract `META-INF/rights.xml` and parse the user ID, resource ID, and encrypted key.

### Test (RED)
- Given a test EPUB file containing `META-INF/rights.xml`, calling the extraction function returns:
  - `user_id` matching `<user>` in rights.xml (e.g. `urn:uuid:0d776b19-...`).
  - `resource_id` matching `<resource>` (e.g. `urn:uuid:77187695-...`).
  - `encrypted_key_b64` matching `<encryptedKey keyInfo="user">`.

### Implementation (GREEN)
- Create `extract_rights(encrypted_epub_path: str) -> dict` in `adept.py`:
  - Open the EPUB as a ZIP archive.
  - Read `META-INF/rights.xml`.
  - Parse XML with namespace handling (elements nested inside `<licenseToken>`).
  - Extract `<user>`, `<resource>`, and `<encryptedKey keyInfo="user">`.
  - Return `{"user_id": str, "resource_id": str, "encrypted_key_b64": str}`.

### Acceptance criteria
- Function returns correct `user_id`, `resource_id`, and base64-encoded encrypted key from a known test EPUB.

---

## Ticket 3: Load RSA private key from ADL database

**Goal:** Given a DB path and user_id, load the `license_priv` (and fall back to `auth_priv`) as a usable RSA private key.

### Test (RED)
- Given a known `adl.db` and the correct user_id from rights.xml, loading the key returns an RSA private key object.
- Given a wrong user_id, raises `ValueError` or returns `None`.

### Implementation (GREEN)
- Create `load_private_key(db_path: str, user_id: str) -> rsa.RSAPrivateKey` in `adept.py`:
  - Connect to SQLite database at `db_path`.
  - Query `SELECT license_priv, auth_priv FROM users WHERE user_id = ?`.
  - Base64-decode the blob to raw DER bytes.
  - Load with `serialization.load_der_private_key(der_bytes, password=None)`.
  - Try `license_priv` first; fall back to `auth_priv` if the first fails.
  - Return the private key object from `cryptography`.

### Acceptance criteria
- Returns a valid RSA private key for the correct user_id from the spike probe's `adl.db`.

---

## Ticket 4: Decrypt the AES content key from rights.xml

**Goal:** RSA-decrypt the encrypted key blob from `rights.xml` using the loaded private key to recover the 16-byte AES-128 content key.

### Test (RED)
- Given the encrypted key bytes from rights.xml and the private key from Ticket 3, decrypting returns exactly 16 bytes.
- Given a wrong private key, decryption raises an error (cryptography exception).

### Implementation (GREEN)
- Create `decrypt_content_key(encrypted_key_bytes: bytes, private_key: rsa.RSAPrivateKey) -> bytes` in `adept.py`:
  - Decode the base64-encoded encrypted key from rights.xml to raw bytes.
  - Call `private_key.decrypt(enc_key_bytes, padding.PKCS1v15())`.
  - Return the resulting bytes (expected: 16-byte AES-128 key).

### Acceptance criteria
- Returns a 16-byte key that matches the known content key from the spike probe.

---

## Ticket 5: Decrypt a single file (AES-CBC + PKCS#7 unpad + raw deflate)

**Goal:** Given encrypted file data and the AES content key, produce the original plaintext bytes.

### Test (RED)
- Given encrypted GIF data from a test EPUB and the correct content key, decrypting produces exactly 15313 bytes matching the reference decrypted EPUB.
- Given encrypted XHTML data, decrypting produces valid XML starting with `<html xmlns=`.

### Implementation (GREEN)
- Create `decrypt_file(encrypted_data: bytes, content_key: bytes) -> bytes` in `adept.py`:
  - Extract IV (first 16 bytes) and ciphertext (remaining).
  - AES-128-CBC decrypt using `Cryptodome.Cipher.AES`.
  - PKCS#7 unpadding — implemented natively in `adept.py` (copied from obok but fully self-contained, no imports from `obok/`).
  - Raw deflate decompress using `zlib.decompress(data, wbits=-zlib.MAX_WBITS)`.
  - Return plaintext bytes.

### Acceptance criteria
- GIF file decryption produces byte-for-byte match with reference decrypted EPUB (15313 bytes).
- XHTML decryption produces valid XML content.

---

## Ticket 6: Parse `encryption.xml` and build encrypted file mapping

**Goal:** Extract the list of encrypted files from `META-INF/encryption.xml` to know which EPUB entries need decryption.

### Test (RED)
- Given a test EPUB with 83 `<EncryptedData>` entries all referencing the same resource UUID, the mapping returns 83 file URIs mapped to that resource ID.

### Implementation (GREEN)
- Extend `extract_rights()` or create a companion function to also parse `META-INF/encryption.xml`:
  - Open EPUB as ZIP, read `META-INF/encryption.xml`.
  - For each `<EncryptedData>`, extract the `<CipherReference URI="...">` and the resource UUID from `<KeyInfo><resource>`.
  - Return a dict mapping file URIs to resource IDs: `{ "OEBPS/path/to/file": "urn:uuid:..." }`.

### Acceptance criteria
- Returns a mapping of all 83 encrypted file URIs to their resource UUID from the test EPUB.

---

## Ticket 7: Full EPUB decryption pipeline — write decrypted output

**Goal:** Given an encrypted EPUB path, decrypt all files and write a valid plaintext `.epub` to the output directory.

### Test (RED)
- Given a known encrypted EPUB and valid ADL DB, calling `decrypt_epub()` produces an output `.epub` file.
- The output EPUB's `mimetype` entry is stored uncompressed (ZIP_STORED).
- All other entries use ZIP_DEFLATED compression.
- The GIF file in the output EPUB matches byte-for-byte with the reference decrypted EPUB.

### Implementation (GREEN)
- Create `decrypt_epub(encrypted_epub_path: str, output_path: str, db_path: str)` in `adept.py`:
  1. Call `extract_rights()` to get rights data and encrypted file mapping.
  2. Match `<user>` from rights.xml to the ADL DB (already handled by `load_private_key`).
  3. Load RSA private key via `load_private_key(db_path, user_id)`.
  4. Decrypt the AES content key via `decrypt_content_key()`.
  5. Open the encrypted EPUB as a ZIP archive.
  6. For each file in encryption.xml: call `decrypt_file()` to get plaintext.
  7. For files NOT in encryption.xml: pass through as-is (unencrypted content).
  8. Create a new ZIP/EPUB:
     - Write `mimetype` first, uncompressed (`ZIP_STORED`).
     - Write all other entries with `ZIP_DEFLATED` compression.
  9. Write the output `.epub` to `output_path`.

### Acceptance criteria
- Running `uv run adl-decode Making\ a\ Career\ in\ Dictatorship-encrypted.epub` produces a valid decrypted `.epub` in `./epub/`.
- The output GIF matches the reference file byte-for-byte.

---

## Ticket 8: Multi-file batch decryption

**Goal:** The CLI accepts multiple EPUB files and decrypts each to the output directory.

### Test (RED)
- `adl-decode book1.epub book2.epub` produces two decrypted `.epub` files in the output directory.
- Each file is independently decrypted using the same ADL DB (same user).

### Implementation (GREEN)
- In `main()`, iterate over all positional EPUB arguments.
- For each, call `decrypt_epub()` with the same DB path and output directory base.
- Output filenames: strip `-encrypted` suffix if present, or use the original name with `.epub`.

### Acceptance criteria
- Multiple EPUB files can be passed on one command line and all are decrypted.

---

## Summary of file structure

```
src/adl/
  adept.py          # New: ADEPT EPUB decryption module + CLI entry point (fully self-contained, no obok/ imports)
  cli.py            # Existing: unchanged (Kobo/ACSM commands)
```

## Dependencies (already present)

- `cryptography` — DER key loading, PKCS1v15 RSA decryption
- `pycryptodomex` (`Cryptodome.Cipher.AES`) — AES-CBC
- `zlib` (stdlib) — raw deflate decompression

No new dependencies needed.

## Execution order

| #  | Ticket                                      | Depends on       |
|----|---------------------------------------------|------------------|
| 1  | CLI entry point with argument parsing       | —                |
| 2  | Extract and parse `rights.xml`              | 1 (functionally) |
| 3  | Load RSA private key from ADL DB            | 1 (functionally) |
| 4  | Decrypt AES content key                     | 2, 3             |
| 5  | Decrypt single file (AES + unpad + deflate) | 4                |
| 6  | Parse `encryption.xml` mapping              | 2 (functionally) |
| 7  | Full EPUB decryption pipeline               | 5, 6             |
| 8  | Multi-file batch decryption                 | 7                |

Tickets 1–3 can be developed in parallel since they are independent functions. Ticket 4 depends on both 2 and 3. Tickets 5–8 build incrementally on prior results.