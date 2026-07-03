"""Tests for AES content key decryption from rights.xml."""

import base64
from pathlib import Path



def _create_test_rsa_keypair(key_size: int = 1024):
    """Generate a test RSA key pair and return (private_key, encrypted_content_key)."""
    from cryptography.hazmat.primitives.asymmetric import rsa as crypto_rsa

    private_key = crypto_rsa.generate_private_key(
        public_exponent=65537, key_size=key_size
    )

    # Simulate the AES content key (16 bytes for AES-128)
    aes_key = b"\x01\x02\x03\x04\x05\x06\x07\x08\x09\x0a\x0b\x0c\x0d\x0e\x0f\x10"

    # Encrypt the AES key with the RSA public key (as ADEPT does)
    public_key = private_key.public_key()
    encrypted = public_key.encrypt(
        aes_key,
        __import__(
            "cryptography.hazmat.primitives.asymmetric"
        ).hazmat.primitives.asymmetric.padding.PKCS1v15(),
    )

    return private_key, encrypted


class TestDecryptContentKey:
    """Tests for RSA-decrypting the AES content key."""

    def test_returns_16_byte_aes_key(self, tmp_path):
        """Given encrypted key bytes and private key, returns 16-byte AES-128 key."""
        from adl.adept import decrypt_content_key

        private_key, encrypted = _create_test_rsa_keypair()
        content_key = decrypt_content_key(encrypted, private_key)

        assert len(content_key) == 16
        assert isinstance(content_key, bytes)

    def test_returns_correct_aes_key(self, tmp_path):
        """The decrypted key matches the original AES key used for encryption."""
        from adl.adept import decrypt_content_key

        private_key, encrypted = _create_test_rsa_keypair()
        original_aes_key = (
            b"\x01\x02\x03\x04\x05\x06\x07\x08\x09\x0a\x0b\x0c\x0d\x0e\x0f\x10"
        )

        content_key = decrypt_content_key(encrypted, private_key)

        assert content_key == original_aes_key

    def test_handles_1024_bit_rsa(self, tmp_path):
        """Works with 1024-bit RSA keys (as used in real ADEPT EPUBs)."""
        from adl.adept import decrypt_content_key

        private_key, encrypted = _create_test_rsa_keypair(key_size=1024)
        content_key = decrypt_content_key(encrypted, private_key)

        assert len(content_key) == 16
        # Ciphertext should be 128 bytes for 1024-bit RSA
        assert len(encrypted) == 128

    def test_handles_2048_bit_rsa(self, tmp_path):
        """Works with 2048-bit RSA keys."""
        from adl.adept import decrypt_content_key

        private_key, encrypted = _create_test_rsa_keypair(key_size=2048)
        content_key = decrypt_content_key(encrypted, private_key)

        assert len(content_key) == 16
        # Ciphertext should be 256 bytes for 2048-bit RSA
        assert len(encrypted) == 256

    def test_raises_on_wrong_key(self, tmp_path):
        """Given a different private key, decryption raises an error."""
        from adl.adept import decrypt_content_key

        _, encrypted = _create_test_rsa_keypair()
        # Generate a different key pair
        other_private, _ = _create_test_rsa_keypair()

        try:
            decrypt_content_key(encrypted, other_private)
            assert False, "Expected cryptography exception"
        except Exception:
            pass

    def test_real_epub_decrypts_to_16_bytes(self):
        """Given the real encrypted EPUB's rights.xml key and ADL DB key, returns 16 bytes."""
        adl_db = Path("~/.adl/adl.db").expanduser()
        encrypted_epub = Path("Making a Career in Dictatorship-encrypted.epub")

        if not adl_db.exists() or not encrypted_epub.exists():
            raise __import__("unittest").SkipTest(
                "Real ADL DB or encrypted EPUB not found"
            )

        from adl.adept import (
            decrypt_content_key,
            extract_rights_and_encryption,
            load_private_key,
        )

        rights_data, _ = extract_rights_and_encryption(str(encrypted_epub))
        user_id = rights_data["user_id"]

        private_key = load_private_key(str(adl_db), user_id)
        encrypted_key_b64 = rights_data["encrypted_key_b64"]

        encrypted_bytes = base64.b64decode(encrypted_key_b64)
        content_key = decrypt_content_key(encrypted_bytes, private_key)

        assert len(content_key) == 16
        # Verify it's a valid AES-128 key (exactly 16 bytes)
        assert isinstance(content_key, bytes)
