"""Adobe ADEPT EPUB decryption using ADL authorization database keys.

This module is fully self-contained and does not import from obok/.
"""

import argparse
import os
import sys
import zipfile
from xml.etree import ElementTree


def extract_rights_and_encryption(encrypted_epub_path: str):
    """Extract and parse META-INF/rights.xml and META-INF/encryption.xml from an EPUB.

    Opens the EPUB as a ZIP archive, reads rights.xml and encryption.xml,
    and parses their contents.

    Args:
        encrypted_epub_path: Path to the ADEPT-protected EPUB file.

    Returns:
        A tuple of (rights_data, encryption_map):
          - rights_data: dict with {user_id, resource_id, encrypted_key_b64},
            or None if rights.xml is not found.
          - encryption_map: dict mapping file URIs to resource IDs,
            or empty dict if encryption.xml is not found.
    """
    rights_data = None
    encryption_map = {}

    with zipfile.ZipFile(encrypted_epub_path) as zf:
        if "META-INF/rights.xml" in zf.namelist():
            rights_xml = zf.read("META-INF/rights.xml")
            root = ElementTree.fromstring(rights_xml)

            user_id = None
            resource_id = None
            encrypted_key_b64 = None

            for elem in root.iter():
                tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag

                if tag == "user":
                    user_id = ("".join(elem.itertext())).strip()
                elif tag == "resource":
                    resource_id = ("".join(elem.itertext())).strip()
                elif tag == "encryptedKey" and elem.get("keyInfo") == "user":
                    encrypted_key_b64 = ("".join(elem.itertext())).strip()

            if user_id and resource_id and encrypted_key_b64:
                rights_data = {
                    "user_id": user_id,
                    "resource_id": resource_id,
                    "encrypted_key_b64": encrypted_key_b64,
                }

        if "META-INF/encryption.xml" in zf.namelist():
            encryption_xml = zf.read("META-INF/encryption.xml")
            root = ElementTree.fromstring(encryption_xml)

            for enc_elem in root.iter():
                tag = (
                    enc_elem.tag.split("}")[-1] if "}" in enc_elem.tag else enc_elem.tag
                )
                if tag == "EncryptedData":
                    cipher_ref = None
                    resource_uuid = None

                    for child in enc_elem.iter():
                        child_tag = (
                            child.tag.split("}")[-1] if "}" in child.tag else child.tag
                        )
                        if child_tag == "CipherReference":
                            cipher_ref = child.get("URI")
                        elif child_tag == "resource":
                            resource_uuid = ("".join(child.itertext())).strip()

                    if cipher_ref and resource_uuid:
                        encryption_map[cipher_ref] = resource_uuid

    return rights_data, encryption_map


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
