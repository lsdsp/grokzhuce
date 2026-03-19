import unittest

from grok_runtime import ErrorType, RuntimeContext


class GrokProtocolTests(unittest.TestCase):
    def test_extract_signup_bootstrap_updates_runtime_from_html_and_bundles(self):
        from grok_protocol import extract_signup_bootstrap

        runtime = RuntimeContext(
            site_key="0x4AAAAAAAhr9JGVDZbrZOo0",
            action_id=None,
            state_tree="fallback",
        )
        html = """
        <html>
          <head>
            <script src="/_next/static/chunks/app.js"></script>
          </head>
          <body>
            <div data-json='{"sitekey":"0x4TESTKEY_123"}'></div>
            <script>window.__x='next-router-state-tree":"encoded-tree-value"';</script>
          </body>
        </html>
        """
        js_bodies = [
            "console.log('noop')",
            "const action='7f1234567890abcdef1234567890abcdef12345678';",
        ]

        result = extract_signup_bootstrap(html=html, js_bodies=js_bodies, runtime=runtime)

        self.assertTrue(result.ok)
        self.assertEqual(runtime.site_key, "0x4TESTKEY_123")
        self.assertEqual(runtime.state_tree, "encoded-tree-value")
        self.assertEqual(runtime.action_id, "7f1234567890abcdef1234567890abcdef12345678")

    def test_extract_signup_bootstrap_reports_parse_error_when_action_id_missing(self):
        from grok_protocol import extract_signup_bootstrap

        runtime = RuntimeContext(
            site_key="0x4AAAAAAAhr9JGVDZbrZOo0",
            action_id=None,
            state_tree="fallback",
        )

        result = extract_signup_bootstrap(
            html='<div data-json=\'{"sitekey":"0x4TESTKEY_123"}\'></div>',
            js_bodies=["console.log('no action id here')"],
            runtime=runtime,
        )

        self.assertFalse(result.ok)
        self.assertEqual(result.error_type, ErrorType.PARSE)
        self.assertIn("Action ID", result.details)

    def test_extract_signup_bootstrap_supports_fallback_patterns_from_html(self):
        from grok_protocol import extract_signup_bootstrap

        runtime = RuntimeContext(
            site_key="0x4AAAAAAAhr9JGVDZbrZOo0",
            action_id=None,
            state_tree="fallback",
        )
        html = """
        <html>
          <head>
            <meta name="next-router-state-tree" content="meta-tree-value" />
          </head>
          <body>
            <script>
              window.__NEXT_DATA__ = {
                "props": {
                  "pageProps": {
                    "siteKey": "0x4FALLBACKKEY_456"
                  }
                }
              };
            </script>
            <div data-next-action="7fabcdefabcdefabcdefabcdefabcdefabcdefabcd"></div>
          </body>
        </html>
        """

        result = extract_signup_bootstrap(
            html=html,
            js_bodies=["console.log('action id not present in bundle')"],
            runtime=runtime,
        )

        self.assertTrue(result.ok)
        self.assertEqual(runtime.site_key, "0x4FALLBACKKEY_456")
        self.assertEqual(runtime.state_tree, "meta-tree-value")
        self.assertEqual(runtime.action_id, "7fabcdefabcdefabcdefabcdefabcdefabcdefabcd")

    def test_extract_signup_bootstrap_parse_error_includes_source_hints(self):
        from grok_protocol import extract_signup_bootstrap

        runtime = RuntimeContext(
            site_key="0x4AAAAAAAhr9JGVDZbrZOo0",
            action_id=None,
            state_tree="fallback",
        )

        result = extract_signup_bootstrap(
            html='<script>window.__NEXT_DATA__={"props":{"pageProps":{"siteKey":"0x4TESTKEY_789"}}}</script>',
            js_bodies=["console.log('still no action here')"],
            runtime=runtime,
        )

        self.assertFalse(result.ok)
        self.assertIn("html_hint", result.details)
        self.assertIn("js_hint", result.details)


if __name__ == "__main__":
    unittest.main()
