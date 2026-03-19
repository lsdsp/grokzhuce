import unittest

from browser_configs import BrowserConfig, browser_config


class BrowserConfigCompatibilityTests(unittest.TestCase):
    def test_browser_config_alias_points_to_browser_config_class(self):
        self.assertIs(browser_config, BrowserConfig)

    def test_browser_config_class_provides_existing_static_methods(self):
        browser_name, version, user_agent, sec_ch_ua = BrowserConfig.get_random_browser_config("camoufox")

        self.assertEqual(browser_name, "chrome")
        self.assertTrue(version)
        self.assertIn("Chrome/", user_agent)
        self.assertIn("Chromium", sec_ch_ua)


if __name__ == "__main__":
    unittest.main()
