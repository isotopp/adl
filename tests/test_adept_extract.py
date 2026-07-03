"""Tests for ADEPT rights.xml and encryption.xml extraction."""

import zipfile

from adl.adept import extract_rights_and_encryption


def _make_test_epub(tmp_path, rights_content=None):
    """Create a minimal EPUB with optional custom rights.xml."""
    epub_path = tmp_path / "test.epub"
    with zipfile.ZipFile(epub_path, "w") as zf:
        zf.writestr(
            "mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED
        )
        zf.writestr(
            "META-INF/container.xml",
            '<?xml version="1.0"?><container version="1.0"><rootfile full-path="OEBPS/content.opf" media-type="application/epub+zip"/></container>',
        )
        zf.writestr(
            "OEBPS/content.opf",
            '<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" version="2.0" unique-identifier="uid"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:opf="http://www.idpf.org/2007/opf"><dc:id idref="uid">urn:uuid:test</dc:id><dc:title>Test</dc:title></metadata><manifest><item id="toc" href="toc.ncx" media-type="application/x-dtbncx+xml"/></manifest><spine><itemref idref="toc"/></spine></package>',
        )
        zf.writestr(
            "OEBPS/toc.ncx",
            '<?xml version="1.0"?><ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1"/><navMap/>',
        )
    return epub_path


def _make_encrypted_epub(tmp_path):
    """Create an EPUB with ADEPT-encrypted content (rights.xml + encryption.xml)."""
    epub_path = tmp_path / "encrypted.epub"

    rights_xml = b"""<?xml version="1.0"?>
<rights xmlns="http://ns.adobe.com/adept">
  <licenseToken>
    <user>urn:uuid:0d776b19-d03e-4e9c-936d-3959f6f08f19</user>
    <resource>urn:uuid:77187695-4844-42fb-baca-d0fc0d10dd3d</resource>
    <encryptedKey keyInfo="user">WYsceFj3rlLxwmk2w21I9wfFjV6pDFcSFQv+Qm6sicDeydWL+FyrqCbOBJ41DaIC9eEdGoHVvGwTP6P6U+pqDHtfLFa1u44yJWJnb5WCXC5IsYUd35hSxmdesJsA1vAaRiz7Dv7Bx5eeDOLIPf1A3dGIi8FY4F071iocql2bfkU=</encryptedKey>
  </licenseToken>
</rights>"""

    encryption_xml = b"""<?xml version="1.0"?>
<encryption xmlns="http://www.w3.org/2001/04/xmlenc#" xmlns:adept="http://ns.adobe.com/adept">
  <EncryptedData>
    <EncryptionMethod Algorithm="http://www.w3.org/2001/04/xmlenc#aes128-cbc"/>
    <KeyInfo><adept:resource xmlns:adept="http://ns.adobe.com/adept">urn:uuid:77187695-4844-42fb-baca-d0fc0d10dd3d</adept:resource></KeyInfo>
    <CipherData><CipherReference URI="OEBPS/chapter1.xhtml"/></CipherData>
  </EncryptedData>
  <EncryptedData>
    <EncryptionMethod Algorithm="http://www.w3.org/2001/04/xmlenc#aes128-cbc"/>
    <KeyInfo><adept:resource xmlns:adept="http://ns.adobe.com/adept">urn:uuid:77187695-4844-42fb-baca-d0fc0d10dd3d</adept:resource></KeyInfo>
    <CipherData><CipherReference URI="OEBPS/chapter2.xhtml"/></CipherData>
  </EncryptedData>
</encryption>"""

    with zipfile.ZipFile(epub_path, "w") as zf:
        zf.writestr(
            "mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED
        )
        zf.writestr(
            "META-INF/container.xml",
            '<?xml version="1.0"?><container version="1.0"><rootfile full-path="OEBPS/content.opf" media-type="application/epub+zip"/></container>',
        )
        zf.writestr("META-INF/rights.xml", rights_xml)
        zf.writestr("META-INF/encryption.xml", encryption_xml)
        zf.writestr(
            "OEBPS/content.opf",
            '<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" version="2.0"><metadata><dc:title>Test</dc:title></metadata></package>',
        )
        zf.writestr("OEBPS/chapter1.xhtml", b"<p>Chapter 1</p>")
        zf.writestr("OEBPS/chapter2.xhtml", b"<p>Chapter 2</p>")
    return epub_path


class TestExtractRights:
    """Tests for rights.xml extraction."""

    def test_returns_user_id(self, tmp_path):
        epub = _make_encrypted_epub(tmp_path)
        rights_data, _ = extract_rights_and_encryption(str(epub))

        assert "user_id" in rights_data
        assert rights_data["user_id"] == "urn:uuid:0d776b19-d03e-4e9c-936d-3959f6f08f19"

    def test_returns_resource_id(self, tmp_path):
        epub = _make_encrypted_epub(tmp_path)
        rights_data, _ = extract_rights_and_encryption(str(epub))

        assert "resource_id" in rights_data
        assert (
            rights_data["resource_id"]
            == "urn:uuid:77187695-4844-42fb-baca-d0fc0d10dd3d"
        )

    def test_returns_encrypted_key(self, tmp_path):
        epub = _make_encrypted_epub(tmp_path)
        rights_data, _ = extract_rights_and_encryption(str(epub))

        assert "encrypted_key_b64" in rights_data
        key = rights_data["encrypted_key_b64"]
        assert len(key) > 0
        # Should be valid base64 (decodable without error)
        import base64

        decoded = base64.b64decode(key)
        assert len(decoded) == 128  # 1024-bit RSA ciphertext

    def test_returns_none_for_epub_without_rights(self, tmp_path):
        epub = _make_test_epub(tmp_path)

        rights_data, encryption_map = extract_rights_and_encryption(str(epub))

        assert rights_data is None
        assert encryption_map == {}


class TestExtractEncryption:
    """Tests for encryption.xml extraction."""

    def test_returns_encrypted_file_mapping(self, tmp_path):
        epub = _make_encrypted_epub(tmp_path)
        _, encryption_map = extract_rights_and_encryption(str(epub))

        assert "OEBPS/chapter1.xhtml" in encryption_map
        assert "OEBPS/chapter2.xhtml" in encryption_map

    def test_mapping_has_resource_uuid(self, tmp_path):
        epub = _make_encrypted_epub(tmp_path)
        _, encryption_map = extract_rights_and_encryption(str(epub))

        for uri, resource_id in encryption_map.items():
            assert resource_id == "urn:uuid:77187695-4844-42fb-baca-d0fc0d10dd3d"

    def test_returns_empty_for_epub_without_encryption(self, tmp_path):
        epub = _make_test_epub(tmp_path)

        _, encryption_map = extract_rights_and_encryption(str(epub))

        assert encryption_map == {}
