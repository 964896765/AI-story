import hashlib
from pathlib import Path
import re
import stat
from .config import STORAGE

MAX_UPLOAD = 2 * 1024**3
WINDOWS_DEVICE = re.compile(r'^(con|prn|aux|nul|com[1-9¹²³]|lpt[1-9¹²³])(?:\.|$)', re.IGNORECASE)

def resolve_key(key: str, root: Path = STORAGE) -> Path:
    parts = key.replace('\\', '/').split('/')
    if any(not part or part in ('.','..') or part.endswith(('.', ' '))
           or re.search(r'[\x00-\x1f:<>?"|*]',part) or WINDOWS_DEVICE.match(part) for part in parts):
        raise ValueError('Invalid storage key')
    root = root.resolve()
    path = root
    for part in parts:
        path = path / part
        try:
            attributes = path.lstat()
        except FileNotFoundError:
            continue
        except NotADirectoryError as exc:
            raise ValueError('Invalid storage key') from exc
        if (stat.S_ISLNK(attributes.st_mode)
            or getattr(attributes,'st_file_attributes',0) & stat.FILE_ATTRIBUTE_REPARSE_POINT):
            raise ValueError('Storage key cannot use a symlink or Windows reparse point')
    resolved = path.resolve()
    if not resolved.is_relative_to(root):
        raise ValueError('Invalid storage key')
    return resolved

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
