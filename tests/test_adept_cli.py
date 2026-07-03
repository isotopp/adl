"""Tests for adl.adept CLI module."""

import os

from adl.adept import build_parser, main


class TestBuildParser:
    """Tests for argument parser construction."""

    def test_default_values(self):
        parser = build_parser()
        args = parser.parse_args([])

        assert args.adl_database == os.path.join(
            os.environ.get("HOME", ""), ".adl", "adl.db"
        )
        assert args.output_directory == "./epub"

    def test_adl_database_argument(self):
        parser = build_parser()
        args = parser.parse_args(["--adl-database", "/custom/path/adl.db"])
        assert args.adl_database == "/custom/path/adl.db"

    def test_output_directory_argument(self):
        parser = build_parser()
        args = parser.parse_args(["--output-directory", "/custom/output"])
        assert args.output_directory == "/custom/output"

    def test_single_epub_argument(self):
        parser = build_parser()
        args = parser.parse_args(["book.epub"])
        assert list(args.epubs) == ["book.epub"]

    def test_multiple_epub_arguments(self):
        parser = build_parser()
        args = parser.parse_args(["book1.epub", "book2.epub"])
        assert list(args.epubs) == ["book1.epub", "book2.epub"]

    def test_help_prints_usage(self):
        parser = build_parser()
        try:
            parser.parse_args(["--help"])
        except SystemExit as e:
            assert e.code == 0


class TestMain:
    """Tests for the main CLI entry point."""

    def test_main_no_epubs_exits_1(self):
        """When no EPUB files are provided, should return 1."""
        result = main([])
        assert result == 1

    def test_main_with_epubs_creates_output_dir(self, tmp_path):
        """When EPUB files are provided, should create output directory."""
        epub_path = tmp_path / "test.epub"
        epub_path.write_bytes(b"fake epub content")

        output_dir = tmp_path / "output"
        args = [str(epub_path), "--output-directory", str(output_dir)]

        result = main(args)
        assert result == 0
        assert output_dir.exists()

    def test_main_with_epubs_and_custom_db(self, tmp_path):
        """When EPUB files are provided with custom DB path, should use it."""
        epub_path = tmp_path / "test.epub"
        epub_path.write_bytes(b"fake epub content")

        db_path = tmp_path / "custom.db"
        db_path.write_bytes(b"fake db content")

        output_dir = tmp_path / "output"
        args = [
            str(epub_path),
            "--adl-database",
            str(db_path),
            "--output-directory",
            str(output_dir),
        ]

        result = main(args)
        assert result == 0
