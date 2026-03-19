from pathlib import Path
import unittest

from grok_runtime import RuntimeContext


FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"


class GrokProtocolSampleTests(unittest.TestCase):
    def test_extract_signup_bootstrap_from_saved_samples(self):
        from grok_protocol_bootstrap import extract_signup_bootstrap

        runtime = RuntimeContext(
            site_key="0x4AAAAAAAhr9JGVDZbrZOo0",
            action_id=None,
            state_tree="fallback-tree",
        )
        html = (FIXTURE_DIR / "bootstrap_signup.html").read_text(encoding="utf-8")
        bundle = (FIXTURE_DIR / "bootstrap_bundle.js").read_text(encoding="utf-8")

        result = extract_signup_bootstrap(html=html, js_bodies=[bundle], runtime=runtime)

        self.assertTrue(result.ok)
        self.assertEqual(runtime.site_key, "0x4AAAAAAB_sampleKey987")
        self.assertEqual(runtime.state_tree, "sample-router-tree-value")
        self.assertEqual(runtime.action_id, "7f1234567890abcdef1234567890abcdef12345678")

    def test_extract_signup_set_cookie_redirect_from_saved_response(self):
        from grok_protocol_signup import extract_set_cookie_redirect_url

        response_text = (FIXTURE_DIR / "signup_success_response.txt").read_text(encoding="utf-8")

        redirect_url = extract_set_cookie_redirect_url(response_text)

        self.assertEqual(
            redirect_url,
            "https://accounts.x.ai/set-cookie?q=sample_redirect_token",
        )


if __name__ == "__main__":
    unittest.main()
