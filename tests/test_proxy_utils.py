import unittest
from unittest.mock import patch

from g.proxy_utils import build_requests_proxies, resolve_proxy_url


class ProxyUtilsTests(unittest.TestCase):
    def test_resolve_proxy_prefers_explicit_key(self):
        with patch.dict(
            "os.environ",
            {
                "GROK_PROXY_URL": "http://127.0.0.1:10808",
                "HTTPS_PROXY": "http://127.0.0.1:9999",
            },
            clear=True,
        ):
            proxy = resolve_proxy_url(preferred_keys=("GROK_PROXY_URL",))

        self.assertEqual(proxy, "http://127.0.0.1:10808")

    def test_build_proxy_falls_back_to_standard_https_proxy(self):
        with patch.dict(
            "os.environ",
            {"HTTPS_PROXY": "http://127.0.0.1:10808"},
            clear=True,
        ):
            proxies = build_requests_proxies(preferred_keys=("GROK_PROXY_URL",))

        self.assertEqual(
            proxies,
            {"http": "http://127.0.0.1:10808", "https": "http://127.0.0.1:10808"},
        )

    def test_build_proxy_supports_lowercase_env(self):
        with patch.dict(
            "os.environ",
            {"all_proxy": "socks5://127.0.0.1:10808"},
            clear=True,
        ):
            proxies = build_requests_proxies(preferred_keys=("GROK_PROXY_URL",))

        self.assertEqual(
            proxies,
            {"http": "socks5://127.0.0.1:10808", "https": "socks5://127.0.0.1:10808"},
        )


if __name__ == "__main__":
    unittest.main()
