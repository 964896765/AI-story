import json
import subprocess
from pathlib import Path

def probe(path: Path) -> dict:
    result = subprocess.run(['ffprobe', '-v', 'error', '-protocol_whitelist', 'file,pipe', '-format_whitelist', 'mov,matroska,webm,avi,wav,mp3', '-show_format', '-show_streams', '-of', 'json', str(path)], capture_output=True, timeout=60, check=False)
    if result.returncode:
        raise ValueError(result.stderr.decode('utf-8', errors='replace')[-3000:])
    data = json.loads(result.stdout)
    if not data.get('streams'):
        raise ValueError('未检测到媒体流')
    return data
