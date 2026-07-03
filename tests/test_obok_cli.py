"""Tests for obok.cli module."""

import zipfile
from unittest.mock import MagicMock, patch


from adl.obok.cli import build_parser, main


class TestBuildParser:
    """Tests for argument parser construction."""

    def test_default_values(self):
        parser = build_parser()
        args = parser.parse_args([])

        assert args.devicedir == ""
        assert args.kobodir == ""
        assert args.decrypt_all is False
        assert args.serials == ""

    def test_devicedir_argument(self):
        parser = build_parser()
        args = parser.parse_args(["--devicedir", "/media/KOBOeReader"])
        assert args.devicedir == "/media/KOBOeReader"

    def test_kobodir_argument(self):
        parser = build_parser()
        args = parser.parse_args(["--kobodir", "/home/user/.local/share/kobo"])
        assert args.kobodir == "/home/user/.local/share/kobo"

    def test_all_flag(self):
        parser = build_parser()
        args = parser.parse_args(["--all"])
        assert args.decrypt_all is True

    def test_serials_argument(self):
        parser = build_parser()
        args = parser.parse_args(["--serials", "abc123,def456,ghi789"])
        assert args.serials == "abc123,def456,ghi789"


class TestMain:
    """Tests for the main CLI entry point."""

    def test_main_no_books(self):
        """When no books are found, should return 1."""
        lib_mock = MagicMock()
        lib_mock.books = []
        lib_mock.kobodir = ""
        lib_mock.bookdir = ""
        lib_mock._cursor = None
        lib_mock.userkeys = []

        with patch("adl.obok.cli.KoboLibrary", return_value=lib_mock):
            result = main(["--all"])

        assert result == 1

    def test_main_interactive_selection(self, tmp_path):
        """Interactive mode should prompt for book selection."""
        # Create a minimal fake epub file so decrypt_book doesn't crash
        book_path = tmp_path / "book.epub"
        with zipfile.ZipFile(book_path, "w") as zf:
            zf.writestr("test.txt", "hello")

        lib_mock = MagicMock()
        book1 = MagicMock()
        book1.title = "Book One"
        book1.has_drm = True
        book1.type = "drm-free"
        book1.filename = str(book_path)

        book2 = MagicMock()
        book2.title = "Book Two"
        book2.has_drm = False
        lib_mock.books = [book1, book2]
        lib_mock.kobodir = ""
        lib_mock.bookdir = ""
        lib_mock._cursor = None
        lib_mock.userkeys = []

        with patch("adl.obok.cli.KoboLibrary", return_value=lib_mock):
            with patch("builtins.input", return_value="1"):
                result = main([])

        assert result == 0

    def test_main_all_flag(self, tmp_path):
        """--all flag should decrypt all books without prompting."""
        book_path1 = tmp_path / "book1.epub"
        with zipfile.ZipFile(book_path1, "w") as zf:
            zf.writestr("test.txt", "hello 1")

        book_path2 = tmp_path / "book2.epub"
        with zipfile.ZipFile(book_path2, "w") as zf:
            zf.writestr("test.txt", "hello 2")

        lib_mock = MagicMock()
        book1 = MagicMock()
        book1.title = "Book One"
        book1.has_drm = False
        book1.type = "drm-free"
        book1.filename = str(book_path1)

        book2 = MagicMock()
        book2.title = "Book Two"
        book2.has_drm = False
        book2.type = "drm-free"
        book2.filename = str(book_path2)

        lib_mock.books = [book1, book2]
        lib_mock.kobodir = ""
        lib_mock.bookdir = ""
        lib_mock._cursor = None
        lib_mock.userkeys = []

        with patch("adl.obok.cli.KoboLibrary", return_value=lib_mock):
            result = main(["--all"])

        assert result == 0

    def test_main_invalid_choice(self):
        """Invalid book selection should return 1."""
        lib_mock = MagicMock()
        book1 = MagicMock()
        book1.title = "Book One"

        lib_mock.books = [book1]
        lib_mock.kobodir = ""
        lib_mock.bookdir = ""
        lib_mock._cursor = None
        lib_mock.userkeys = []

        with patch("adl.obok.cli.KoboLibrary", return_value=lib_mock):
            with patch("builtins.input", return_value="invalid"):
                result = main([])

        assert result == 1

    def test_main_with_serials(self, tmp_path):
        """Serials should be parsed and passed to KoboLibrary."""
        book_path = tmp_path / "book.epub"
        with zipfile.ZipFile(book_path, "w") as zf:
            zf.writestr("test.txt", "hello")

        lib_mock = MagicMock()
        book1 = MagicMock()
        book1.title = "Book One"
        book1.type = "drm-free"
        book1.filename = str(book_path)

        lib_mock.books = [book1]
        lib_mock.kobodir = ""
        lib_mock.bookdir = ""
        lib_mock._cursor = None
        lib_mock.userkeys = []

        with patch("adl.obok.cli.KoboLibrary") as lib_cls:
            lib_cls.return_value = lib_mock
            main(["--serials", "abc123,def456", "--all"])

        lib_cls.assert_called_once_with(
            serials=["abc123", "def456"],
            device_path=None,
            desktop_kobodir="",
        )

    def test_main_with_devicedir(self, tmp_path):
        """Device dir should be passed to KoboLibrary."""
        book_path = tmp_path / "book.epub"
        with zipfile.ZipFile(book_path, "w") as zf:
            zf.writestr("test.txt", "hello")

        lib_mock = MagicMock()
        book1 = MagicMock()
        book1.title = "Book One"
        book1.type = "drm-free"
        book1.filename = str(book_path)

        lib_mock.books = [book1]
        lib_mock.kobodir = ""
        lib_mock.bookdir = ""
        lib_mock._cursor = None
        lib_mock.userkeys = []

        with patch("adl.obok.cli.KoboLibrary") as lib_cls:
            lib_cls.return_value = lib_mock
            main(["--devicedir", "/media/KOBOeReader", "--all"])

        lib_cls.assert_called_once_with(
            serials=[],
            device_path="/media/KOBOeReader",
            desktop_kobodir="",
        )
