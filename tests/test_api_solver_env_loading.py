import importlib
import os
import sys
import unittest
from unittest.mock import patch


class ApiSolverEnvLoadingTests(unittest.TestCase):
    def test_api_solver_loads_env_before_importing_solver_modules(self):
        modules_to_reset = [
            "api_solver",
            "solver_server",
            "solver_result_repository",
            "db_results",
        ]

        saved_modules = {name: sys.modules.get(name) for name in modules_to_reset}
        for name in modules_to_reset:
            sys.modules.pop(name, None)

        def fake_load_project_env(*args, **kwargs):
            os.environ["SOLVER_RESULT_STORE"] = "sqlite"
            os.environ["SOLVER_RESULT_DB_PATH"] = ":memory:"
            return True

        try:
            with patch.dict(os.environ, {}, clear=False):
                os.environ.pop("SOLVER_RESULT_STORE", None)
                os.environ.pop("SOLVER_RESULT_DB_PATH", None)
                with patch("grok_env.load_project_env", side_effect=fake_load_project_env):
                    api_solver = importlib.import_module("api_solver")

            self.assertEqual(api_solver.load_project_env.call_count, 1)

            import db_results

            self.assertEqual(
                db_results.default_result_store.__class__.__name__,
                "SQLiteSolverResultStore",
            )
        finally:
            for name in modules_to_reset:
                sys.modules.pop(name, None)
            for name, module in saved_modules.items():
                if module is not None:
                    sys.modules[name] = module


if __name__ == "__main__":
    unittest.main()
