from context import api_call, bom, data, xml_tools
from unittest.mock import patch
import unittest
import httpx
from pathlib import Path

# Capture the real generate_signature at module load time to restore after pollution
_real_generate_signature = xml_tools.generate_signature

TEST_DIR = Path(__file__).resolve().parent


class TestAPICallTimeout(unittest.TestCase):
    def setUp(self):
        """Restore xml_tools.generate_signature if a prior test polluted it."""
        xml_tools.generate_signature = _real_generate_signature

    def test_post_uses_default_timeout(self):
        """FFAuth.call() succeeds; verify httpx.post was called with default timeout."""
        d = bom.Device()
        d.device_key = 1
        d.name = "local"

        a = bom.Account()
        a.urn = "toto"
        a.licenseCertificate = b"LICENSECERT"
        a.devices = [d]

        c = bom.Config()
        c.current_user = "toto"
        c.authentication_certificate = b"AUTHCERT"

        data.config = c
        data.accounts = [a]

        default_timeout = (10, 30)

        with (
            patch("adl.utils.extract_cert_from_pkcs12", return_value=b"DEADBEEF"),
            patch("adl.utils.extract_pk_from_pkcs12", return_value="DEADBEEF"),
            patch("adl.utils.make_nonce", return_value="11Mo2AAAAAA="),
            patch(
                "adl.utils.get_expiration_date",
                return_value="2021-04-15T23:27:34-00:00",
            ),
            patch("adl.xml_tools.generate_signature", return_value="0123456789ABCDEF"),
            patch("httpx.post") as mock_post,
        ):
            request = httpx.Request("POST", "http://fairyland.com/Auth")
            mock_post.return_value = httpx.Response(
                text="success", status_code=200, request=request
            )

            ff = api_call.FFAuth("http://fairyland.com", a, c)
            result = ff.call()

            self.assertTrue(result)
            mock_post.assert_called_once()
            call_kwargs = mock_post.call_args[1]
            self.assertEqual(call_kwargs.get("timeout"), default_timeout)

    def test_get_uses_default_timeout(self):
        """ActivationInit.call() succeeds; verify httpx.get was called with default timeout."""
        c = api_call.ActivationInit()

        default_timeout = (10, 30)

        with patch("httpx.get") as mock_get:
            request = httpx.Request(
                "GET", "http://adeactivate.adobe.com/adept/ActivationServiceInfo"
            )
            reply = b'<activationServiceInfo xmlns="http://ns.adobe.com/adept"><authURL>http://adeactivate.adobe.com/adept</authURL><userInfoURL>http://adeactivate.adobe.com/adept/userinfo</userInfoURL><certificate>TOTO</certificate></activationServiceInfo>'
            mock_get.return_value = httpx.Response(
                text=reply.decode(), status_code=200, request=request
            )

            result = c.call()

            self.assertEqual(
                result,
                (
                    "http://adeactivate.adobe.com/adept",
                    "http://adeactivate.adobe.com/adept/userinfo",
                    "TOTO",
                ),
            )
            mock_get.assert_called_once()
            call_kwargs = mock_get.call_args[1]
            self.assertEqual(call_kwargs.get("timeout"), default_timeout)

    def test_connect_timeout_propagates(self):
        """Server does not respond within connect time; verify ConnectTimeout propagates."""
        d = bom.Device()
        d.device_key = 1
        d.name = "local"

        a = bom.Account()
        a.urn = "toto"
        a.licenseCertificate = b"LICENSECERT"
        a.devices = [d]

        c = bom.Config()
        c.current_user = "toto"
        c.authentication_certificate = b"AUTHCERT"

        ff = api_call.FFAuth("http://fairyland.com", a, c)

        with (
            patch("adl.utils.extract_cert_from_pkcs12", return_value=b"DEADBEEF"),
            patch("adl.utils.extract_pk_from_pkcs12", return_value="DEADBEEF"),
            patch("adl.utils.make_nonce", return_value="11Mo2AAAAAA="),
            patch(
                "adl.utils.get_expiration_date",
                return_value="2021-04-15T23:27:34-00:00",
            ),
            patch("adl.xml_tools.generate_signature", return_value="0123456789ABCDEF"),
            patch("httpx.post") as mock_post,
        ):
            mock_post.side_effect = httpx.ConnectTimeout("timed out")

            with self.assertRaises(httpx.ConnectTimeout):
                ff.call()

    def test_read_timeout_propagates(self):
        """Server connects but stalls; verify ReadTimeout propagates."""
        d = bom.Device()
        d.device_key = 1
        d.name = "local"

        a = bom.Account()
        a.urn = "toto"
        a.licenseCertificate = b"LICENSECERT"
        a.devices = [d]

        c = bom.Config()
        c.current_user = "toto"
        c.authentication_certificate = b"AUTHCERT"

        ff = api_call.FFAuth("http://fairyland.com", a, c)

        with (
            patch("adl.utils.extract_cert_from_pkcs12", return_value=b"DEADBEEF"),
            patch("adl.utils.extract_pk_from_pkcs12", return_value="DEADBEEF"),
            patch("adl.utils.make_nonce", return_value="11Mo2AAAAAA="),
            patch(
                "adl.utils.get_expiration_date",
                return_value="2021-04-15T23:27:34-00:00",
            ),
            patch("adl.xml_tools.generate_signature", return_value="0123456789ABCDEF"),
            patch("httpx.post") as mock_post,
        ):
            mock_post.side_effect = httpx.ReadTimeout("timed out")

            with self.assertRaises(httpx.ReadTimeout):
                ff.call()

    def test_non_2xx_returns_none(self):
        """Server returns 500; existing behavior preserved — returns None."""
        d = bom.Device()
        d.device_key = 1
        d.name = "local"

        a = bom.Account()
        a.urn = "toto"
        a.licenseCertificate = b"LICENSECERT"
        a.devices = [d]

        c = bom.Config()
        c.current_user = "toto"
        c.authentication_certificate = b"AUTHCERT"

        ff = api_call.FFAuth("http://fairyland.com", a, c)

        with (
            patch("adl.utils.extract_cert_from_pkcs12", return_value=b"DEADBEEF"),
            patch("adl.utils.extract_pk_from_pkcs12", return_value="DEADBEEF"),
            patch("adl.utils.make_nonce", return_value="11Mo2AAAAAA="),
            patch(
                "adl.utils.get_expiration_date",
                return_value="2021-04-15T23:27:34-00:00",
            ),
            patch("adl.xml_tools.generate_signature", return_value="0123456789ABCDEF"),
            patch("httpx.post") as mock_post,
        ):
            request = httpx.Request("POST", "http://fairyland.com/Auth")
            mock_post.return_value = httpx.Response(
                status_code=500, text="Server Error", request=request
            )

            result = ff.call()
            self.assertFalse(result)


if __name__ == "__main__":
    unittest.main()
