import os
from pathlib import Path


def _default_storage_root():
    if os.path.exists("/home/pi"):
        return Path("/home/pi/task_manager/storage")
    return Path.home() / "task_manager" / "storage"


DATABASE_URL = os.getenv("DATABASE_URL", "")
STORAGE_ROOT = Path(os.getenv("STORAGE_ROOT", str(_default_storage_root())))
TASK_PACKAGE_DIR = STORAGE_ROOT / "tasks"
RESULT_PACKAGE_DIR = STORAGE_ROOT / "results"
TEMP_DIR = STORAGE_ROOT / "temp"

REDIS_HOST = os.getenv("REDIS_HOST", "127.0.0.1")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))


def ensure_storage_dirs():
    for directory in (TASK_PACKAGE_DIR, RESULT_PACKAGE_DIR, TEMP_DIR):
        directory.mkdir(parents=True, exist_ok=True)
