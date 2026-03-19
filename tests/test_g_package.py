import importlib
import unittest
from unittest.mock import patch

import g


class GPackageTests(unittest.TestCase):
    def test_exports_are_loaded_lazily(self):
        module = importlib.reload(g)
        module.__dict__.pop("EmailService", None)

        with patch("g.import_module") as import_module_mock:
            sentinel_cls = object()
            fake_module = type("FakeModule", (), {"EmailService": sentinel_cls})
            import_module_mock.return_value = fake_module

            value = module.EmailService

        self.assertIs(value, sentinel_cls)
        import_module_mock.assert_called_once_with(".email_service", "g")


if __name__ == "__main__":
    unittest.main()
