import os
from dotenv import load_dotenv

load_dotenv()

SECRET_KEY    = os.environ["SECRET_KEY"]
MY1409_BASE   = os.environ.get("MY1409_BASE", "https://my1409.ru").rstrip("/")
ADMIN_PW_HASH = os.environ["ADMIN_PW_HASH"]
DATABASE_URL  = os.environ["DATABASE_URL"]