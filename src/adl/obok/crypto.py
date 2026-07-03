"""Low-level crypto helpers for Kobo DRM."""


def unpad(data: bytes, padding: int = 16) -> bytes:
    """Remove PKCS#7 padding from decrypted data."""
    pad_len = data[-1]
    return data[:-pad_len]
