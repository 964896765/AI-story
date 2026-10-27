import hashlib
from pathlib import Path
from .config import STORAGE

MAX_UPLOAD = 2 * 1024**3

def resolve_key(key: str, root: Path = STORAGE) -> Path:
    path = (root / key).resolve()
    if not path.is_relative_to(root.resolve()) or path == root.resolve():
        raise ValueError('Invalid storage key')
    return path

async def save_upload(upload, key: str, max_bytes: int | None = None):
    path = resolve_key(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    digest, size = hashlib.sha256(), 0
    created = False
    try:
        with path.open('xb') as out:
            created = True
            while chunk := await upload.read(1024 * 1024):
                size += len(chunk)
                if size > (max_bytes if max_bytes is not None else MAX_UPLOAD):
                    raise ValueError('文件超过允许的大小上限')
                digest.update(chunk)
                out.write(chunk)
        if not size:
            raise ValueError('不允许空文件')
    except Exception:
        if created:
            path.unlink(missing_ok=True)
        raise
    return digest.hexdigest(), size
