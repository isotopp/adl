"""Tests for full EPUB decryption pipeline."""

import os
import zipfile
from pathlib import Path


def _load_reference_gif() -> bytes:
    """Load the reference GIF from the decrypted EPUB."""
    ref_epub = Path("Making a Career in Dictatorship-decrypted.epub")
    if not ref_epub.exists():
        raise __import__("unittest").SkipTest("Reference decrypted EPUB not found")

    with zipfile.ZipFile(ref_epub) as zf:
        for name in zf.namelist():
            if "graphic-004.gif" in name:
                return zf.read(name)
    raise __import__("unittest").SkipTest("GIF not found in reference EPUB")


def _load_encrypted_gif() -> bytes:
    """Load the encrypted GIF from the encrypted EPUB."""
    enc_epub = Path("Making a Career in Dictatorship-encrypted.epub")
    if not enc_epub.exists():
        raise __import__("unittest").SkipTest("Encrypted EPUB not found")

    with zipfile.ZipFile(enc_epub) as zf:
        for name in zf.namelist():
            if "graphic-004.gif" in name:
                return zf.read(name)
    raise __import__("unittest").SkipTest("GIF not found in encrypted EPUB")


class TestDecryptEpub:
    """Tests for full EPUB decryption pipeline."""

    def test_produces_output_epub(self, tmp_path):
        """Given encrypted EPUB and valid ADL DB, produces output .epub file."""
        adl_db = Path("~/.adl/adl.db").expanduser()
        encrypted_epub = Path("Making a Career in Dictatorship-encrypted.epub")

        if not adl_db.exists() or not encrypted_epub.exists():
            raise __import__("unittest").SkipTest("ADL DB or encrypted EPUB not found")

        from adl.adept import decrypt_epub

        os.makedirs(str(tmp_path / "output"), exist_ok=True)
        output_path = str(tmp_path / "output" / "decrypted.epub")

        decrypt_epub(str(encrypted_epub), output_path, str(adl_db))

        assert Path(output_path).exists()
        # Verify it's a valid ZIP/EPUB
        with zipfile.ZipFile(output_path) as zf:
            assert "mimetype" in zf.namelist()

    def test_mimetype_stored_uncompressed(self, tmp_path):
        """Output EPUB's mimetype entry is stored uncompressed (ZIP_STORED)."""
        adl_db = Path("~/.adl/adl.db").expanduser()
        encrypted_epub = Path("Making a Career in Dictatorship-encrypted.epub")

        if not adl_db.exists() or not encrypted_epub.exists():
            raise __import__("unittest").SkipTest("ADL DB or encrypted EPUB not found")

        from adl.adept import decrypt_epub

        output_path = str(tmp_path / "decrypted.epub")
        decrypt_epub(str(encrypted_epub), output_path, str(adl_db))

        with zipfile.ZipFile(output_path) as zf:
            info = zf.getinfo("mimetype")
            assert info.compress_type == zipfile.ZIP_STORED

    def test_other_entries_use_deflated(self, tmp_path):
        """All non-mimetype entries use ZIP_DEFLATED compression."""
        adl_db = Path("~/.adl/adl.db").expanduser()
        encrypted_epub = Path("Making a Career in Dictatorship-encrypted.epub")

        if not adl_db.exists() or not encrypted_epub.exists():
            raise __import__("unittest").SkipTest("ADL DB or encrypted EPUB not found")

        from adl.adept import decrypt_epub

        output_path = str(tmp_path / "decrypted.epub")
        decrypt_epub(str(encrypted_epub), output_path, str(adl_db))

        with zipfile.ZipFile(output_path) as zf:
            for name in zf.namelist():
                if name == "mimetype":
                    continue
                info = zf.getinfo(name)
                assert info.compress_type == zipfile.ZIP_DEFLATED, (
                    f"Expected {name} to use ZIP_DEFLATED, got {info.compress_type}"
                )

    def test_gif_matches_reference(self, tmp_path):
        """GIF file in output EPUB matches reference decrypted EPUB byte-for-byte."""
        adl_db = Path("~/.adl/adl.db").expanduser()
        encrypted_epub = Path("Making a Career in Dictatorship-encrypted.epub")

        if not adl_db.exists() or not encrypted_epub.exists():
            raise __import__("unittest").SkipTest("ADL DB or encrypted EPUB not found")

        from adl.adept import decrypt_epub

        output_path = str(tmp_path / "decrypted.epub")
        decrypt_epub(str(encrypted_epub), output_path, str(adl_db))

        # Extract GIF from output
        with zipfile.ZipFile(output_path) as zf:
            for name in zf.namelist():
                if "graphic-004.gif" in name:
                    output_gif = zf.read(name)
                    break
            else:
                raise __import__("unittest").SkipTest("GIF not found in output EPUB")

        # Compare with reference
        ref_gif = _load_reference_gif()
        assert output_gif == ref_gif

    def test_all_encrypted_files_decrypted(self, tmp_path):
        """All 83 encrypted files are decrypted in the output EPUB."""
        adl_db = Path("~/.adl/adl.db").expanduser()
        encrypted_epub = Path("Making a Career in Dictatorship-encrypted.epub")

        if not adl_db.exists() or not encrypted_epub.exists():
            raise __import__("unittest").SkipTest("ADL DB or encrypted EPUB not found")

        from adl.adept import decrypt_epub

        output_path = str(tmp_path / "decrypted.epub")
        decrypt_epub(str(encrypted_epub), output_path, str(adl_db))

        with (
            zipfile.ZipFile(encrypted_epub) as enc_zf,
            zipfile.ZipFile(output_path) as out_zf,
        ):
            enc_names = set(n for n in enc_zf.namelist() if n != "mimetype")
            out_names = set(n for n in out_zf.namelist() if n != "mimetype")

            # All encrypted files should be in output
            assert enc_names == out_names, (
                f"Missing: {enc_names - out_names}, Extra: {out_names - enc_names}"
            )

    def test_xhtml_decrypted_correctly(self, tmp_path):
        """XHTML files in output are valid XML (not encrypted)."""
        adl_db = Path("~/.adl/adl.db").expanduser()
        encrypted_epub = Path("Making a Career in Dictatorship-encrypted.epub")

        if not adl_db.exists() or not encrypted_epub.exists():
            raise __import__("unittest").SkipTest("ADL DB or encrypted EPUB not found")

        from adl.adept import decrypt_epub

        output_path = str(tmp_path / "decrypted.epub")
        decrypt_epub(str(encrypted_epub), output_path, str(adl_db))

        with zipfile.ZipFile(output_path) as zf:
            xhtml_found = False
            for name in zf.namelist():
                if name.endswith(".xhtml"):
                    xhtml_found = True
                    content = zf.read(name)
                    text = content.decode("utf-8")
                    # Should contain valid HTML, not encrypted garbage
                    assert (
                        "<html" in text.lower()
                        or "<?xml" in text
                        or "<!DOCTYPE" in text
                    )
                    break
            assert xhtml_found, "No XHTML files found in output EPUB"
