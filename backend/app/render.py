"""Validated local FFmpeg pipeline. All process arguments are an argv list."""
import hashlib
import json
import math
import os
import queue
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Literal, Callable
from pydantic import BaseModel, ConfigDict, Field, model_validator
from .media import probe
from .storage import resolve_key
from .process_guard import attach

def file_hash(path: Path, update=None) -> str:
    digest=hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda:source.read(1024*1024),b''):
            digest.update(chunk)
            if update:update('checkpoint',99)
    return digest.hexdigest()

def write_manifest(path: Path, data: dict):
    staging=path.with_suffix('.writing')
    with staging.open('w',encoding='utf-8') as file:
        json.dump(data,file,ensure_ascii=False)
        file.flush();os.fsync(file.fileno())
    os.replace(staging,path)

class Cancelled(Exception):
    pass

class RenderOptions(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    start: float = Field(default=0, ge=0, le=86400)
    end: float | None = Field(default=None, gt=0, le=86400)
    duration: float | None = Field(default=None, gt=0, le=86400)
    aspect: Literal['original','9:16','16:9','1:1'] = 'original'
    strategy: Literal['crop','fit','pad'] = 'pad'
    resolution: Literal['source','720','1080','1440','2160'] = 'source'
    format: Literal['mp4','mkv'] = 'mp4'
    crf: int = Field(default=18, ge=0, le=28)
    audio_mode: Literal['keep','replace','mute'] = 'keep'
    audio_asset_id: str | None = None
    subtitle_asset_id: str | None = None
    volume: float = Field(default=1, ge=0, le=4)

    @model_validator(mode='after')
    def validate_options(self):
        if self.end is not None and self.end <= self.start:
            raise ValueError('结束时间必须大于开始时间')
        if self.duration is not None and self.end is not None:
            raise ValueError('结束时间和裁剪时长只能填写一项')
        if (self.audio_mode == 'replace') != bool(self.audio_asset_id):
            raise ValueError('替换音轨时必须选择音频素材；其他模式不得指定替换音轨')
        return self

def clip_duration(options: RenderOptions, source_duration: float) -> float:
    if not math.isfinite(source_duration) or source_duration <= 0:
        raise ValueError('源视频时长无效')
    duration = options.duration if options.duration is not None else (options.end or source_duration) - options.start
    if options.start >= source_duration or duration <= 0 or options.start + duration > source_duration + 0.05:
        raise ValueError('裁剪范围超出源视频时长')
    return min(duration, source_duration - options.start)

def display_size(stream: dict) -> tuple[int,int]:
    width, height = int(stream['width']), int(stream['height'])
    sar = stream.get('sample_aspect_ratio', '1:1').split(':')
    if len(sar) == 2 and sar[0].isdigit() and sar[1].isdigit() and int(sar[1]):
        width = round(width * int(sar[0]) / int(sar[1]))
    rotation = float(stream.get('tags', {}).get('rotate', 0))
    for side in stream.get('side_data_list', []):
        rotation = float(side.get('rotation', rotation))
    if round(rotation) % 180 == 90:
        width, height = height, width
    if min(width,height) <= 0:
        raise ValueError('视频分辨率无效')
    return width,height

def geometry(options: RenderOptions, stream: dict) -> tuple[str,tuple[int,int]]:
    width,height = display_size(stream)
    ratio = width/height if options.aspect == 'original' else float(options.aspect.split(':')[0])/float(options.aspect.split(':')[1])
    short = min(width,height) if options.resolution == 'source' else int(options.resolution)
    target = (round(short*max(ratio,1)), round(short*max(1/ratio,1)))
    even = lambda n: max(2, int(n)//2*2)
    tw,th = map(even,target)
    if options.aspect == 'original' and options.resolution == 'source':
        tw,th = even(width),even(height)
    if max(tw,th)>8192 or tw*th>36_000_000:
        raise ValueError('输出尺寸超过本机安全上限（8192 边长 / 3600 万像素）')
    if options.strategy == 'fit':
        factor = min(tw/width, th/height)
        fw,fh = even(width*factor),even(height*factor)
        return f'scale={fw}:{fh}:flags=lanczos,setsar=1', (fw,fh)
    if options.strategy == 'crop':
        factor = max(tw/width, th/height)
        sw,sh = math.ceil(width*factor/2)*2,math.ceil(height*factor/2)*2
        return f'scale={sw}:{sh}:flags=lanczos,crop={tw}:{th},setsar=1', (tw,th)
    factor = min(tw/width, th/height)
    sw,sh = even(width*factor),even(height*factor)
    return f'scale={sw}:{sh}:flags=lanczos,pad={tw}:{th}:(ow-iw)/2:(oh-ih)/2:black,setsar=1', (tw,th)

def validate_srt(path: Path) -> str:
    if path.stat().st_size > 2 * 1024**2:
        raise ValueError('SRT 超过 2 MiB')
    content = path.read_text(encoding='utf-8-sig').replace('\r\n','\n').strip()
    cues = re.split(r'\n\s*\n', content)
    pattern = re.compile(r'^(\d+):(\d{2}):(\d{2}),(\d{3}) --> (\d+):(\d{2}):(\d{2}),(\d{3})$')
    for cue in cues:
        lines = cue.splitlines()
        if len(lines) < 3 or not lines[0].isdigit():
            raise ValueError('SRT 格式无效（需要 UTF-8、序号、时间行和字幕文本）')
        match = pattern.fullmatch(lines[1])
        if not match:
            raise ValueError('SRT 时间格式无效')
        values = list(map(int,match.groups()))
        if any(values[i] >= 60 for i in (1,2,5,6)):
            raise ValueError('SRT 分秒超出范围')
        def seconds(v): return v[0]*3600+v[1]*60+v[2]+v[3]/1000
        if seconds(values[:4]) >= seconds(values[4:]):
            raise ValueError('SRT 时间范围无效')
    return content+'\n'

def stop_process(process):
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)

def execute_ffmpeg(args: list[str], work: Path, duration: float, update: Callable, timeout: float = 21600):
    lines: queue.Queue = queue.Queue(maxsize=256)
    def drain(pipe):
        try:
            for line in pipe:
                try: lines.put_nowait(line.strip())
                except queue.Full: pass
        finally:
            pipe.close()
    with (work/'ffmpeg.log').open('w',encoding='utf-8') as errors:
        process = subprocess.Popen(args, cwd=work, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=errors, text=True, encoding='utf-8', errors='replace')
        try:
            close_job = attach(process)
        except Exception:
            stop_process(process)
            process.stdout.close()
            raise
        thread = threading.Thread(target=drain,args=(process.stdout,),daemon=True)
        thread.start()
        started, last, seconds = time.monotonic(), 0.0, 0.0
        try:
            while True:
                while not lines.empty():
                    line = lines.get_nowait()
                    if line.startswith('out_time_us='):
                        try: seconds = max(seconds,float(line.split('=',1)[1])/1_000_000)
                        except ValueError: pass
                current = time.monotonic()
                if current-last >= 0.5:
                    update('encoding', min(99.0, seconds/duration*100))
                    last = current
                if current-started > timeout:
                    raise TimeoutError('FFmpeg 超时（6 小时上限）')
                if process.poll() is not None:
                    break
                time.sleep(0.1)
            thread.join(timeout=2)
            if process.returncode:
                raise RuntimeError('FFmpeg 编码失败：'+(work/'ffmpeg.log').read_text(encoding='utf-8',errors='replace')[-4000:])
        finally:
            stop_process(process)
            close_job()

def validate_output(path: Path, expected: dict) -> dict:
    info = probe(path)
    videos = [s for s in info['streams'] if s['codec_type']=='video' and not s.get('disposition',{}).get('attached_pic')]
    audios = [s for s in info['streams'] if s['codec_type']=='audio']
    duration = float(info.get('format',{}).get('duration',0))
    if not videos or path.stat().st_size == 0:
        raise ValueError('成片缺少视频流或内容为空')
    if tuple((videos[0]['width'],videos[0]['height'])) != tuple(expected['size']):
        raise ValueError('成片分辨率不符合配置')
    if abs(duration-expected['duration']) > max(0.3,expected['duration']*0.02):
        raise ValueError('成片时长不符合裁剪范围')
    if bool(audios) != expected['audio']:
        raise ValueError('成片音轨不符合配置')
    if audios:
        audio_duration = float(audios[0].get('duration',duration))
        if abs(audio_duration-expected['duration']) > max(0.3,expected['duration']*0.02):
            raise ValueError('成片音轨时长异常')
    rotation = [s.get('rotation',0) for s in videos[0].get('side_data_list',[])]
    if any(abs(float(r)) > 0.1 for r in rotation):
        raise ValueError('成片旋转信息未归一化')
    return {'duration':duration,'width':videos[0]['width'],'height':videos[0]['height'],'has_audio':bool(audios),'size_bytes':path.stat().st_size}

def render(task_id: str, attempt: int, parameters: dict, inputs: dict, update: Callable) -> dict:
    options = RenderOptions(**parameters)
    source = resolve_key(inputs['video']['storage_key'])
    work = resolve_key(f'tmp/{task_id}/{attempt}')
    work.mkdir(parents=True,exist_ok=True)
    target_key = f'outputs/{task_id}/video.{options.format}'
    target = resolve_key(target_key)
    signature = hashlib.sha256(json.dumps({'options':parameters,'inputs':inputs},sort_keys=True).encode()).hexdigest()
    update('inspecting',0)
    for item in inputs.values():
        path = resolve_key(item['storage_key'])
        h=hashlib.sha256()
        with path.open('rb') as file:
            for chunk in iter(lambda:file.read(1024*1024),b''):
                h.update(chunk)
                update('inspecting',0)
        digest=h.hexdigest()
        if digest != item['sha256']:
            raise ValueError('输入素材哈希不符，拒绝处理已改变的文件')
    info = probe(source)
    video = next((s for s in info['streams'] if s['codec_type']=='video' and not s.get('disposition',{}).get('attached_pic')),None)
    if not video:
        raise ValueError('输入素材没有视频流')
    pixel_format = video.get('pix_fmt','')
    if video.get('color_transfer') in ('smpte2084','arib-std-b67') or re.search(r'(?:p|le|be)(?:9|10|12|14|16)',pixel_format) or pixel_format.startswith(('p010','p012','p016')) or int(video.get('bits_per_raw_sample') or 8)>8:
        raise ValueError('当前 H.264 8-bit 输出不支持 HDR/高位深素材，拒绝静默降低画质；请另行准备 SDR 8-bit 授权源素材')
    duration = clip_duration(options,float(info['format'].get('duration',0)))
    vf,size = geometry(options,video)
    has_audio = options.audio_mode == 'replace' or (options.audio_mode=='keep' and any(s['codec_type']=='audio' for s in info['streams']))
    expected = {'duration':duration,'size':size,'audio':has_audio}
    manifest = work/'manifest.json'
    # A previous attempt may have published before the DB commit. Reconcile, never overwrite.
    if target.exists():
        previous = target.parent/'manifest.json'
        if not previous.exists() or json.loads(previous.read_text())['signature'] != signature:
            raise ValueError('成片路径已有无法确认归属的文件，拒绝覆盖')
        saved=json.loads(previous.read_text(encoding='utf-8'))
        if saved.get('sha256') and saved['sha256']!=file_hash(target,update):
            raise ValueError('已发布成片哈希不符，拒绝将改变的文件视为成功')
        metadata = validate_output(target,expected)
        return {**metadata,'storage_key':target_key,'signature':signature,'recovered':True}
    if shutil.disk_usage(work).free < max(256*1024**2, source.stat().st_size*2):
        raise OSError('磁盘剩余空间不足（至少保留 256 MiB 且不低于源文件的两倍）')
    args = ['ffmpeg','-hide_banner','-nostdin','-n','-loglevel','warning','-filter_threads','2','-progress','pipe:1','-stats_period','0.5','-protocol_whitelist','file,pipe','-format_whitelist','mov,matroska,webm,avi,wav,mp3','-ss',str(options.start),'-i',str(source)]
    if options.audio_mode == 'replace':
        audio = resolve_key(inputs['audio']['storage_key'])
        if not any(s['codec_type']=='audio' for s in probe(audio)['streams']):
            raise ValueError('替换素材没有音频流')
        args += ['-protocol_whitelist','file,pipe','-format_whitelist','mov,matroska,webm,avi,wav,mp3','-i',str(audio)]
    if options.subtitle_asset_id:
        (work/'subtitle.srt').write_text(validate_srt(resolve_key(inputs['subtitle']['storage_key'])),encoding='utf-8')
        vf += ',subtitles=filename=subtitle.srt:charenc=UTF-8'
    args += ['-map',f"0:{int(video['index'])}",'-vf',vf,'-map_metadata','-1','-metadata:s:v:0','rotate=0','-c:v','libx264','-preset','medium','-crf',str(options.crf),'-pix_fmt','yuv420p','-fps_mode','passthrough','-threads','2']
    if has_audio:
        args += ['-map','1:a:0' if options.audio_mode=='replace' else '0:a:0','-af',f'volume={options.volume},aresample=async=1:first_pts=0,apad','-c:a','aac','-b:a','192k']
    else:
        args += ['-an']
    temporary = work/f'partial.{options.format}'
    # Every attempt has its own directory. A restarted attempt always receives a new number.
    args += ['-t',str(duration)]
    if options.format=='mp4': args += ['-movflags','+faststart']
    args.append(str(temporary))
    (work/'command.json').write_text(json.dumps(args,ensure_ascii=False,indent=2),encoding='utf-8')
    candidate=None
    for number in range(attempt-1,0,-1):
        prior=resolve_key(f'tmp/{task_id}/{number}')
        checkpoint=prior/'manifest.json'
        partial=prior/f'partial.{options.format}'
        if checkpoint.is_file() and partial.is_file():
            try:saved=json.loads(checkpoint.read_text(encoding='utf-8'))
            except (ValueError,OSError):continue
            if saved.get('signature')==signature and saved.get('sha256')==file_hash(partial,update):
                try:validate_output(partial,expected)
                except (ValueError,OSError):continue
                candidate=(partial,number);break
    try:
        if candidate:
            update('resuming_checkpoint',99)
            temporary=candidate[0]
        else:
            execute_ffmpeg(args,work,duration,update)
            write_manifest(manifest,{'signature':signature,'expected':expected,'sha256':file_hash(temporary,update)})
        update('validating',99)
        metadata = validate_output(temporary,expected)
        payload={'signature':signature,'expected':expected,'metadata':metadata,'sha256':file_hash(temporary,update)}
        write_manifest(manifest,payload)
        update('publishing',99)
        target.parent.mkdir(parents=True,exist_ok=True)
        # Manifest first enables crash recovery if publication succeeds before DB commit.
        manifest_target = target.parent/'manifest.json'
        if manifest_target.exists():
            if json.loads(manifest_target.read_text())['signature'] != signature:
                raise ValueError('输出清单冲突，拒绝覆盖')
            write_manifest(manifest_target,payload)
        else:
            staging=work/'publish-manifest.json'
            write_manifest(staging,payload)
            os.link(staging,manifest_target)
        # Windows rename fails if target exists. os.link is also no-clobber on other OSes.
        os.link(temporary,target)
        temporary.unlink()
        return {**metadata,'storage_key':target_key,'signature':signature,'recovered':False,'resumed_from_attempt':candidate[1] if candidate else None}
    finally:
        # Valid encoded checkpoints survive interruption/cancellation for safe retry.
        if not manifest.is_file():temporary.unlink(missing_ok=True)
