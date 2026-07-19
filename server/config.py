import logging
import os
import secrets
import time
from pathlib import Path

log = logging.getLogger("dq1.config")

# Wall-clock process start (uptime /time for multiplayer ops)
PROCESS_STARTED_AT = time.time()

BASE_DIR = Path(__file__).resolve().parent
ROOT_DIR = BASE_DIR.parent
DATA_DIR = ROOT_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

# Optional .env load (no dependency)
_env_path = ROOT_DIR / ".env"
if _env_path.is_file():
    for line in _env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

ENV = os.getenv("ENV", os.getenv("DQ1_ENV", "development")).lower()
IS_PROD = ENV in ("production", "prod")

DATABASE_URL = os.getenv("DATABASE_URL", str(DATA_DIR / "dq1_mmo.db"))

_default_secret = "dev-secret-change-me-in-production"
SECRET_KEY = os.getenv("SECRET_KEY", "")
if not SECRET_KEY:
    if IS_PROD:
        raise RuntimeError("SECRET_KEY must be set in production")
    SECRET_KEY = _default_secret
    log.warning("Using insecure default SECRET_KEY (dev only)")
elif SECRET_KEY == _default_secret and IS_PROD:
    raise RuntimeError("Refusing to run production with default SECRET_KEY")

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "10080"))

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
GOOGLE_REDIRECT_URI = os.getenv(
    "GOOGLE_REDIRECT_URI", "http://localhost:8000/auth/google/callback"
)

HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()]

# Debug encounters: default on in dev, off in prod
_allow_dbg = os.getenv("ALLOW_DEBUG")
if _allow_dbg is None:
    ALLOW_DEBUG = not IS_PROD
else:
    ALLOW_DEBUG = _allow_dbg not in ("0", "false", "False")

STARTING_GOLD = os.getenv("STARTING_GOLD", "300")

# Combat reconnect grace (seconds) — battle kept if player returns in time
COMBAT_GRACE_SECONDS = float(os.getenv("COMBAT_GRACE_SECONDS", "60"))

VERSION = "0.5.119"

# Multiplayer message of the day (shown on /motd and optional join)
MOTD = os.getenv(
    "MOTD",
    "Welcome to DQ1 MMO — share the overworld, fight fair, be kind.",
)


def new_secret_hint() -> str:
    return secrets.token_urlsafe(32)
