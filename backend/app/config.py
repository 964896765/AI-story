import os
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / '.env')
_storage = Path(os.getenv('STORAGE_ROOT', 'data'))
STORAGE = (_storage if _storage.is_absolute() else ROOT / _storage).resolve()
DATABASE_URL = os.getenv('DATABASE_URL', 'postgresql+psycopg://story:unconfigured@127.0.0.1:5432/story')
ORIGIN = os.getenv('FRONTEND_ORIGIN', 'http://127.0.0.1:15173')
