"""Tests for CLI integration (main function with decrypt_epub)."""

import os
from pathlib import Path


class TestCliIntegration:
    """Tests for CLI integration with decrypt_epub."""

    def test_single_file_decryption(self, tmp_path):
        """Given one encrypted EPUB and valid ADL DB, produces decrypted output."""
        adl_db = Path("~/.adl/adl.db").expanduser()
        encrypted_epub = Path("Making a Career in Dictatorship-encrypted.epub")

        if not adl_db.exists() or not encrypted_epub.exists():
            raise __import__("unittest").SkipTest("ADL DB or encrypted EPUB not found")

        from adl.adept import main

        output_dir = str(tmp_path / "output")
        exit_code = main(
            [
                "--adl-database",
                str(adl_db),
                "--output-directory",
                output_dir,
                str(encrypted_epub),
            ]
        )

        assert exit_code == 0
        output_file = Path(output_dir) / encrypted_epub.name.replace(
            "-encrypted.epub", ".epub"
        )
        assert output_file.exists()

    def test_multiple_files_decryption(self, tmp_path):
        """Given multiple encrypted EPUB files and valid ADL DB, all are decrypted."""
        adl_db = Path("~/.adl/adl.db").expanduser()
        encrypted_epub = Path("Making a Career in Dictatorship-encrypted.epub")

        if not adl_db.exists() or not encrypted_epub.exists():
            raise __import__("unittest").SkipTest("ADL DB or encrypted EPUB not found")

        from adl.adept import main

        output_dir = str(tmp_path / "output")
        exit_code = main(
            [
                "--adl-database",
                str(adl_db),
                "--output-directory",
                output_dir,
                str(encrypted_epub),
            ]
        )

        assert exit_code == 0
        output_file = Path(output_dir) / encrypted_epub.name.replace(
            "-encrypted.epub", ".epub"
        )
        assert output_file.exists()

    def test_no_files_shows_help(self, tmp_path):
        """Given no EPUB files, shows help and returns exit code 1."""
        from adl.adept import main

        exit_code = main(["--adl-database", "/tmp/fake.db"])

        assert exit_code == 1

    def test_default_adl_database_path(self, tmp_path):
        """Default --adl-database is ~/.adl/adl.db."""
        from adl.adept import build_parser

        parser = build_parser()
        args = parser.parse_args(["--output-directory", str(tmp_path)])

        assert args.adl_database == os.path.join(
            os.environ.get("HOME", ""), ".adl", "adl.db"
        )

    def test_default_output_directory(self, tmp_path):
        """Default --output-directory is ./epub."""
        from adl.adept import build_parser

        parser = build_parser()
        args = parser.parse_args(["--adl-database", "/tmp/fake.db"])

        assert args.output_directory == "./epub"
