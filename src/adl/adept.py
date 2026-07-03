"""Adobe ADEPT EPUB decryption using ADL authorization database keys.

This module is fully self-contained and does not import from obok/.
"""

import argparse
import os
import sys


def build_parser():
    """Build the argument parser for adl-decode."""
    parser = argparse.ArgumentParser(
        description="Decrypt ADEPT-protected EPUB files using ADL database keys."
    )
    parser.add_argument(
        "epubs",
        nargs="*",
        help="EPUB files to decrypt.",
    )
    parser.add_argument(
        "--adl-database",
        default=os.path.join(os.environ.get("HOME", ""), ".adl", "adl.db"),
        help="Path to the ADL authorization database (default: ~/.adl/adl.db).",
    )
    parser.add_argument(
        "--output-directory",
        default="./epub",
        help="Directory to write decrypted EPUBs (default: ./epub).",
    )
    return parser


def main(argv=None):
    """Main entry point for adl-decode CLI.

    Parses arguments, creates output directory, and returns exit code.
    Decryption logic is implemented in subsequent tickets.

    Returns:
        int: 0 on success, 1 if no EPUB files provided.
    """
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.epubs:
        parser.print_help()
        return 1

    os.makedirs(args.output_directory, exist_ok=True)

    return 0


if __name__ == "__main__":
    sys.exit(main())
