"""One explicitly authorized Images API request, with an injectable test transport."""
import base64
from dataclasses import dataclass
import json
import os
import re
import struct
import zlib

import httpx

from .text_adapters import CallFailure

BASE_URL = 'https://api.openai.com/v1'
SIZES = {'square': (1024,1024), 'portrait': (1024,1536), 'landscape': (1536,1024)}
MAX_IMAGE = 20 * 1024**2
MAX_RESPONSE = 4 * ((MAX_IMAGE+2)//3) + 65536


@dataclass(frozen=True)
class ImageResult:
    content: bytes
    request_id: str | None = None
    usage: dict | None = None


def simulation(profile):
    width,height = SIZES[profile]

    def chunk(kind, data):
        return struct.pack('>I',len(data)) + kind + data + struct.pack('>I',zlib.crc32(kind+data))

    palette = [(18,27,49),(30,85,132),(47,143,149),(206,173,95)]
    pixels = bytearray()
    for y in range(height):
        offset = (y//64) % len(palette)
        pixels.extend(b'\0'+b''.join(bytes(palette[(index+offset)%len(palette)]) * (width//4) for index in range(4)))
    header = struct.pack('>IIBBBBB',width,height,8,2,0,0,0)
    return ImageResult(b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',header)+chunk(b'IDAT',zlib.compress(pixels))+chunk(b'IEND',b''))


def generate(model, prompt, profile, credential, request_id, *, transport=None):
    if not credential:
        raise CallFailure('IMAGE_KEY_MISSING')
    if transport is None and (os.getenv('AI_STORY_ENABLE_PAID_IMAGE')!='1'
        or os.getenv('AI_STORY_BUDGET_GUARD_APPROVED')!='1' or not os.getenv('AI_STORY_LIVE_AUTHORIZATION_ID')
        or os.getenv(os.getenv('AI_STORY_IMAGE_SECRET_ENV',''))!=credential
        or os.getenv('AI_STORY_IMAGE_MODEL')!=model):
        raise CallFailure('IMAGE_DISPATCH_NOT_AUTHORIZED')
    width,height = SIZES[profile]
    payload = {'model':model,'prompt':prompt,'size':f'{width}x{height}',
               'quality':'medium','n':1,'output_format':'png','stream':False}
    headers = {'Authorization':'Bearer '+credential,'X-Client-Request-Id':request_id}
    try:
        with httpx.Client(transport=transport,timeout=httpx.Timeout(150,connect=5),
                          follow_redirects=False,trust_env=False) as client:
            with client.stream('POST',BASE_URL+'/images/generations',json=payload,headers=headers) as response:
                if response.status_code!=200:
                    raise CallFailure(f'IMAGE_HTTP_{response.status_code}_UNKNOWN',True)
                raw = bytearray()
                for chunk in response.iter_bytes(chunk_size=65536):
                    raw.extend(chunk)
                    if len(raw)>MAX_RESPONSE:
                        raise CallFailure('IMAGE_RESPONSE_TOO_LARGE',True)
                data = json.loads(raw)
                if not isinstance(data,dict) or not isinstance(data.get('data'),list) or len(data['data'])!=1:
                    raise ValueError('Unexpected image envelope')
                item = data['data'][0]
                encoded = item.get('b64_json') if isinstance(item,dict) else None
                if not isinstance(encoded,str) or not encoded:
                    raise ValueError('Image bytes required')
                content = base64.b64decode(encoded,validate=True)
                if not content or len(content)>MAX_IMAGE:
                    raise ValueError('Invalid image byte length')
                vendor_id = response.headers.get('x-request-id','')
                if credential in vendor_id or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,200}',vendor_id):
                    vendor_id = None
                usage = data.get('usage')
                counts = {key:usage[key] for key in ('input_tokens','output_tokens','total_tokens')
                          if isinstance(usage,dict) and type(usage.get(key)) is int and 0<=usage[key]<10**9}
                return ImageResult(content,vendor_id,counts or None)
    except (httpx.HTTPError,UnicodeError,ValueError,RecursionError):
        raise CallFailure('IMAGE_RESPONSE_OUTCOME_UNKNOWN',True) from None
