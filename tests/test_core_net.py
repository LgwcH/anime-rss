from __future__ import annotations

import ssl
import unittest
import urllib.error
import urllib.request

from anirss.core.net import SafeRedirectHandler, tls_context


class SafeRedirectHandlerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.handler = SafeRedirectHandler()

    def redirect(self, source: str, target: str) -> urllib.request.Request | None:
        request = urllib.request.Request(source)
        return self.handler.redirect_request(request, None, 302, "Found", {}, target)

    def test_refuses_https_downgrade(self) -> None:
        with self.assertRaises(urllib.error.HTTPError):
            self.redirect("https://example.test/feed", "http://example.test/feed")

    def test_refuses_non_http_schemes(self) -> None:
        with self.assertRaises(urllib.error.HTTPError):
            self.redirect("https://example.test/feed", "ftp://example.test/feed")

    def test_allows_same_or_upgraded_schemes(self) -> None:
        redirected = self.redirect("https://example.test/feed", "https://cdn.example.test/feed")
        assert redirected is not None
        self.assertEqual(redirected.full_url, "https://cdn.example.test/feed")
        upgraded = self.redirect("http://example.test/feed", "https://example.test/feed")
        assert upgraded is not None
        self.assertEqual(upgraded.full_url, "https://example.test/feed")


class TlsContextTests(unittest.TestCase):
    def test_verifying_context_uses_defaults(self) -> None:
        context = tls_context(verify=True)
        self.assertTrue(context.check_hostname)
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)

    def test_unverified_context_uses_public_api(self) -> None:
        context = tls_context(verify=False)
        self.assertFalse(context.check_hostname)
        self.assertEqual(context.verify_mode, ssl.CERT_NONE)


if __name__ == "__main__":
    unittest.main()
