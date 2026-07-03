"""Command-line interface for Kobo DRM removal."""

from __future__ import annotations

import argparse
import sys

from adl.obok.models import KoboLibrary, decrypt_book


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser."""
    from adl.obok import __about__

    parser = argparse.ArgumentParser(
        prog="obok",
        description=__about__,
    )
    parser.add_argument(
        "--devicedir",
        default="",
        help="Directory of connected Kobo device (e.g. /media/KOBOeReader)",
    )
    parser.add_argument(
        "--kobodir",
        default="",
        help="Path to Kobo Desktop Edition data directory",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        dest="decrypt_all",
        help="Decrypt all books in the library",
    )
    parser.add_argument(
        "--serials",
        default="",
        help="Comma-separated list of device serial numbers",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point for the obok CLI."""
    from adl.obok import __about__

    print(__about__)

    parser = build_parser()
    args = parser.parse_args(argv)

    # Parse serials if provided
    serials = (
        [s.strip() for s in args.serials.split(",") if s.strip()]
        if args.serials
        else []
    )

    lib = KoboLibrary(
        serials=serials,
        device_path=args.devicedir or None,
        desktop_kobodir=args.kobodir or "",
    )

    try:
        books = list(lib.books)

        if not books:
            print("No books found in library.")
            return 1

        # Interactive selection unless --all is passed
        if args.decrypt_all:
            to_decrypt = books
        else:
            for i, book in enumerate(books):
                drm_tag = " [DRM]" if book.has_drm else ""
                print(f"{i + 1}: {book.title}{drm_tag}")
            print("Or 'all'")

            choice = input("Convert book number... ")
            if choice.strip().lower() == "all":
                to_decrypt = list(books)
            else:
                try:
                    num = int(choice.strip())
                    to_decrypt = [books[num - 1]]
                except (ValueError, IndexError):
                    print("Invalid choice. Exiting...")
                    return 1

        results = [decrypt_book(book, lib) for book in to_decrypt]

        if all(result != 0 for result in results):
            print("Could not decrypt books with any of the keys found.")
            return 1

        return 0
    finally:
        lib.close()


if __name__ == "__main__":
    sys.exit(main())
