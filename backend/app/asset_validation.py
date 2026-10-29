from pathlib import Path
import struct

IMAGE_SUFFIXES={'.png','.jpg','.jpeg','.webp'}

def validate_extra_asset(path:Path,suffix:str):
    if suffix=='.txt':
        content=path.read_text(encoding='utf-8-sig')
        if not content.strip():raise ValueError('文本文件为空或仅包含空白')
    elif suffix in IMAGE_SUFFIXES:
        with path.open('rb') as file:header=file.read(32)
        if suffix=='.png':
            if len(header)<24 or header[:8]!=b'\x89PNG\r\n\x1a\n' or header[12:16]!=b'IHDR':raise ValueError('PNG文件头无效')
            width,height=struct.unpack('>II',header[16:24])
            if not 0<width<=16384 or not 0<height<=16384:raise ValueError('PNG尺寸超过限制')
        elif suffix in ('.jpg','.jpeg'):
            if not header.startswith(b'\xff\xd8\xff'):raise ValueError('JPEG文件头无效')
        elif not (header[:4]==b'RIFF' and header[8:12]==b'WEBP'):
            raise ValueError('WebP文件头无效')
