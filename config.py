import os
from dotenv import load_dotenv

load_dotenv()

SECRET_KEY   = os.environ.get("SECRET_KEY", "dev-secret-key-change-in-production")
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://localhost:5432/study1409")
ADMIN_PW_HASH = os.environ.get("ADMIN_PW_HASH", "")
MY1409_BASE  = os.environ.get("MY1409_BASE", "https://my1409.ru").rstrip("/")
