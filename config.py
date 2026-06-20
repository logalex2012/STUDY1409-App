import os
from dotenv import load_dotenv

load_dotenv()

SECRET_KEY  = os.environ["SECRET_KEY"]
MY1409_BASE = os.environ.get("MY1409_BASE", "https://my1409.ru").rstrip("/")