"""
Centralized Configuration Loader
Loads from .env file or system environment variables.
"""

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
ENV_FILE = PROJECT_ROOT / ".env"


def _load_dotenv(path: Path):
    """Zero-dependency .env parser that loads variables into os.environ."""
    if not path.exists():
        return
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            key = key.strip()
            val = val.strip().strip("'\"")
            # Only set if not already present in environment
            if key not in os.environ:
                os.environ[key] = val


# Load .env into environment
_load_dotenv(ENV_FILE)

# 01. Video Storage Providers
VIDARA_API_KEY = os.getenv("VIDARA_API_KEY", "cc6630108e04a26c58513a923b643e1d30e5c6295b9052100ab4e0578d13aa32")
SAVEFILES_API_KEY = os.getenv("SAVEFILES_API_KEY", "12788yw4xeco1sk20glq0")
PLAYMATE_API_KEY = os.getenv("PLAYMATE_API_KEY", "deaf804d60034a3e2a42ccf4a0cfd2b8f6ce1f892f00cea2cba52e57dba7d052")
BYSE_API_KEY = os.getenv("BYSE_API_KEY", "48397uaa9vk8w0su5yrjw")

# 02. Turso Cloud Database
TURSO_DATABASE_URL = os.getenv("TURSO_DATABASE_URL", "").strip()
TURSO_AUTH_TOKEN = os.getenv("TURSO_AUTH_TOKEN", "").strip()
IS_TURSO_ENABLED = bool(TURSO_DATABASE_URL and TURSO_AUTH_TOKEN)

# 03. Telegram Webhook Alerts
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()
IS_TELEGRAM_ENABLED = bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)

# 04. App Settings & CORS
API_BASE_URL = os.getenv("API_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
ALLOWED_ORIGINS = [orig.strip() for orig in os.getenv("ALLOWED_ORIGINS", "*").split(",") if orig.strip()]
DEFAULT_CONCURRENCY = int(os.getenv("DEFAULT_CONCURRENCY", "6"))
