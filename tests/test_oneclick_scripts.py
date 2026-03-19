from pathlib import Path
import unittest


PROJECT_ROOT = Path(__file__).resolve().parent.parent


class OneClickScriptIntegrationTests(unittest.TestCase):
    def test_start_all_scripts_load_shared_defaults(self):
        ps1 = (PROJECT_ROOT / "start_all.ps1").read_text(encoding="utf-8")
        sh = (PROJECT_ROOT / "start_all.sh").read_text(encoding="utf-8")
        smoke = (PROJECT_ROOT / "release_smoke.ps1").read_text(encoding="utf-8")

        self.assertIn("oneclick_shared.py defaults", ps1)
        self.assertIn("oneclick_shared.py defaults", sh)
        self.assertIn("oneclick_shared.py defaults", smoke)

    def test_start_all_scripts_share_failure_patterns_summary(self):
        ps1 = (PROJECT_ROOT / "start_all.ps1").read_text(encoding="utf-8")
        sh = (PROJECT_ROOT / "start_all.sh").read_text(encoding="utf-8")

        self.assertIn("oneclick_shared.py failure-patterns", ps1)
        self.assertIn("oneclick_shared.py failure-patterns", sh)
        self.assertIn("Show-GrokFailureSummary", ps1)
        self.assertIn("show_grok_failure_summary", sh)

    def test_start_all_ps1_avoids_powershell7_only_null_coalescing_operator(self):
        ps1 = (PROJECT_ROOT / "start_all.ps1").read_text(encoding="utf-8")

        self.assertNotIn("??", ps1)


if __name__ == "__main__":
    unittest.main()
