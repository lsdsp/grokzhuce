from pathlib import Path

from dotenv import load_dotenv


_ENV_LOADED = False


def load_project_env(force: bool = False) -> bool:
    """Load the project-local .env exactly once by default."""
    global _ENV_LOADED

    if _ENV_LOADED and not force:
        return False

    env_path = Path(__file__).resolve().parent / ".env"
    load_dotenv(dotenv_path=env_path)
    _ENV_LOADED = True
    return env_path.exists()
