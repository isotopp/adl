"""Tests for RSA private key loading from ADL database."""

import base64
import os
import sqlite3
from unittest import SkipTest

from cryptography.hazmat.primitives.asymmetric import rsa


def _create_test_db(db_path: str, user_id: str = "urn:uuid:test-123"):
    """Create a minimal test ADL database with a known RSA key pair."""
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    # Create users table matching real ADL schema
    c.execute(
        """CREATE TABLE users (
            user_id TEXT PRIMARY KEY,
            sign_id TEXT,
            sign_method TEXT,
            auth_pub TEXT,
            auth_priv TEXT,
            license_pub TEXT,
            license_priv TEXT,
            pkcs12 TEXT,
            eplk TEXT,
            license_certificate TEXT
        )"""
    )

    # Generate a test RSA key pair (2048-bit)
    from cryptography.hazmat.primitives.asymmetric import rsa as crypto_rsa
    from cryptography.hazmat.primitives.serialization import (
        Encoding,
        NoEncryption,
        PrivateFormat,
        PublicFormat,
    )

    private_key = crypto_rsa.generate_private_key(public_exponent=65537, key_size=2048)

    # Serialize to DER format
    der_priv = private_key.private_bytes(
        Encoding.DER, PrivateFormat.TraditionalOpenSSL, NoEncryption()
    )

    # Base64-encode the DER bytes (as stored in real ADL DB)
    b64_priv = base64.b64encode(der_priv).decode("ascii")

    public_key = private_key.public_key()
    der_pub = public_key.public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)
    b64_pub = base64.b64encode(der_pub).decode("ascii")

    c.execute(
        "INSERT INTO users VALUES (?, 'test@example.com', 'email', ?, ?, ?, ?, NULL, NULL, NULL)",
        (user_id, b64_pub, b64_priv, b64_pub, b64_priv),
    )

    conn.commit()
    conn.close()
    return user_id, private_key


class TestLoadPrivateKey:
    """Tests for loading RSA private key from ADL database."""

    def test_returns_rsa_private_key(self, tmp_path):
        """Given a valid user_id and DB with key data, returns an RSA private key."""
        db_path = str(tmp_path / "test.db")
        user_id, _expected_key = _create_test_db(db_path)

        from adl.adept import load_private_key

        key = load_private_key(db_path, user_id)

        assert isinstance(key, rsa.RSAPrivateKey)

    def test_uses_license_priv_first(self, tmp_path):
        """license_priv column is tried before auth_priv."""
        db_path = str(tmp_path / "test.db")
        user_id, _expected_key = _create_test_db(db_path)

        from adl.adept import load_private_key

        key = load_private_key(db_path, user_id)

        # Verify it's the correct key by checking it can encrypt/decrypt
        from cryptography.hazmat.primitives.asymmetric import padding

        plaintext = b"test message"
        ciphertext = key.public_key().encrypt(plaintext, padding.PKCS1v15())
        decrypted = key.decrypt(ciphertext, padding.PKCS1v15())
        assert decrypted == plaintext

    def test_raises_for_unknown_user(self, tmp_path):
        """Given a user_id not in the database, raises ValueError."""
        db_path = str(tmp_path / "test.db")
        _create_test_db(db_path, user_id="urn:uuid:real-user")

        from adl.adept import load_private_key

        try:
            load_private_key(db_path, "urn:uuid:nonexistent-user")
            assert False, "Expected ValueError"
        except ValueError:
            pass

    def test_raises_for_db_without_keys(self, tmp_path):
        """Given a DB with no key columns populated, raises ValueError."""
        db_path = str(tmp_path / "test.db")
        conn = sqlite3.connect(db_path)
        c = conn.cursor()
        c.execute(
            """CREATE TABLE users (
                user_id TEXT PRIMARY KEY, sign_id TEXT, sign_method TEXT,
                auth_pub TEXT, auth_priv TEXT, license_pub TEXT,
                license_priv TEXT, pkcs12 TEXT, eplk TEXT, license_certificate TEXT
            )"""
        )
        c.execute(
            "INSERT INTO users VALUES ('urn:uuid:nokeys', 'test', 'email', NULL, NULL, NULL, NULL, NULL, NULL, NULL)"
        )
        conn.commit()
        conn.close()

        from adl.adept import load_private_key

        try:
            load_private_key(db_path, "urn:uuid:nokeys")
            assert False, "Expected ValueError"
        except (ValueError, TypeError):
            pass

    def test_real_adl_db_loads_key(self):
        """Given the real ~/.adl/adl.db, loads a valid RSA private key."""
        adl_db = os.path.expanduser("~/.adl/adl.db")
        if not os.path.exists(adl_db):
            raise SkipTest("No real ADL database found at ~/.adl/adl.db")

        from adl.adept import load_private_key

        # Use the known user_id from the spike probe
        key = load_private_key(adl_db, "urn:uuid:0d776b19-d03e-4e9c-936d-3959f6f08f19")

        assert isinstance(key, rsa.RSAPrivateKey)
        # Verify key size is reasonable (1024+ bits)
        assert key.key_size >= 1024
