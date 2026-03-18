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


if __name__ == "__main__":
    unittest.main()
