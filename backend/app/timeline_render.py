"""Render a fixed integer-frame timeline as H.264/AAC using local FFmpeg."""
from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
import re
import shutil
from pathlib import Path

from . import storage
from .analysis_engine import Commands
from .generation import DEMUXERS, SIZES, image_dimensions
from .media import probe
from .render import execute_ffmpeg, file_hash, validate_output, validate_srt, write_manifest
from .story_schemas import Timeline


FPS = 24
RATE = 48000
SAMPLES_PER_FRAME = RATE // FPS
ENGINE = 'timeline-24fps-v1'
VISUAL = {'main','overlay'}
AUDIO = {'dialogue','music','sfx'}
TIMESTAMP = re.compile(r'(\d+):(\d{2}):(\d{2}),(\d{3})')
MEDIA_FORMATS = 'mov,matroska,webm,avi,wav,mp3'
MUSIC_DUCKING_PRESET = 'ffmpeg-sidechain-dialogue-v1'


def sec(frames):
    return f'{frames/FPS:.9f}'


def source_duration(stream, info):
    for value in (stream.get('duration'), info['format'].get('duration')):
        try:
            result = Decimal(str(value))
        except InvalidOperation:
            continue
        if result.is_finite() and result>0:
            return result
    raise ValueError('素材流未提供有效时长')


def stream_for(info,kind):
    return next((stream for stream in info['streams'] if stream['codec_type']==kind
                 and not stream.get('disposition',{}).get('attached_pic')),None)


def verify_range(info, stream, clip):
    expected = Decimal(clip.source_in+clip.frames)/FPS
    if expected-source_duration(stream,info)>Decimal(1)/FPS:
        raise ValueError(f'片段 {clip.id} 的源区间超出素材时长')


def show_dimensions(width,height,role):
    if role=='overlay':
        width,height = width//6*2,height//6*2
    return width,height


def crop_filter(width,height):
    return (f'scale={width}:{height}:force_original_aspect_ratio=decrease:force_divisible_by=2,'
            f'pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black,setsar=1')


def video_filter(index, clip, source, image, info, width,height,role):
    transform = crop_filter(width,height)
    if image:
        if clip.source_in:
            raise ValueError('静图的源入点必须为 0')
        image_dimensions(source,DEMUXERS[source.suffix.lower()])
        zoom = f'1+0.12*on/{max(1,clip.frames-1)}' if clip.still_motion=='push_in' else '1'
        filters = (f'{transform},zoompan=z={zoom}:x=(iw-iw/zoom)/2:y=(ih-ih/zoom)/2:'
                   f'd={clip.frames}:s={width}x{height}:fps={FPS}')
        label = f'{index}:v:0'
    else:
        stream=stream_for(info,'video')
        if not stream:
            raise ValueError('所选画面素材无视频流')
        if clip.still_motion!='none':
            raise ValueError('静图运镜只适用于图片素材')
        if stream.get('color_transfer') in ('smpte2084','arib-std-b67') or stream.get('pix_fmt') not in {
            'yuv420p','yuvj420p','nv12','yuv422p','yuvj422p','yuv444p','yuvj444p',
        }:
            raise ValueError('时间轴画面仅接受 SDR 8-bit YUV 或静态图片')
        if max(stream['width'],stream['height'])>8192 or stream['width']*stream['height']>36_000_000:
            raise ValueError('视频输入尺寸超过安全上限')
        verify_range(info,stream,clip)
        filters = (f'{transform},fps={FPS},tpad=stop_mode=clone:stop_duration={sec(1)},'
                   f'trim=start_frame={clip.source_in}:end_frame={clip.source_in+clip.frames}')
        label = f"{index}:{stream['index']}"
    if role=='overlay':
        filters += ',format=yuva420p'
    else:
        filters += ',format=yuv420p'
    if clip.fade_in:
        filters += f",fade=t=in:s=0:n={clip.fade_in}:alpha={int(role=='overlay')}"
    if clip.fade_out:
        filters += f",fade=t=out:s={clip.frames-clip.fade_out}:n={clip.fade_out}:alpha={int(role=='overlay')}"
    return f'[{label}]{filters},settb=1/{FPS},setpts=N+{clip.at}[clipv{index}]'


def audio_filter(index,clip,info,volume):
    stream = stream_for(info,'audio')
    if not stream:
        raise ValueError('所选声音素材没有音轨')
    verify_range(info,stream,clip)
    start = clip.source_in*SAMPLES_PER_FRAME
    samples = clip.frames*SAMPLES_PER_FRAME
    filters = (f'aresample={RATE},aformat=sample_fmts=fltp:channel_layouts=stereo,'
               f'atrim=start_sample={start}:end_sample={start+samples},asetpts=PTS-STARTPTS,volume={volume}')
    if clip.fade_in:
        filters += f',afade=t=in:ss=0:ns={clip.fade_in*SAMPLES_PER_FRAME}'
    if clip.fade_out:
        filters += f',afade=t=out:ss={(clip.frames-clip.fade_out)*SAMPLES_PER_FRAME}:ns={clip.fade_out*SAMPLES_PER_FRAME}'
    filters += f',adelay={clip.at*SAMPLES_PER_FRAME}S:all=1'
    return f"[{index}:{stream['index']}]{filters}[clipa{index}]"


def audio_mix(labels,frames,*,limit=False):
    mix = ''.join(labels)+f'amix=inputs={len(labels)}:duration=longest:normalize=0,'
    if limit:
        mix += 'alimiter=limit=0.94:level=false:latency=true,'
    return mix+f'apad,atrim=end_sample={frames*SAMPLES_PER_FRAME}'


def music_ducking_applies(timeline):
    roles = {track.role for track in timeline.tracks if track.enabled and track.volume and track.clips}
    return timeline.music_ducking and {'dialogue', 'music'} <= roles


def duck_music(graph, dialogue, music, frames):
    # Match the block boundaries and timestamps of both compressor inputs, including their final partial blocks.
    frame_audio = ',asetnsamples=n=1024:p=0,asetpts=N/SR/TB'
    graph.append(audio_mix(dialogue,frames)+frame_audio+'[dialogueBus]')
    graph.append('[dialogueBus]asplit=2[heardDialogue][dialogueKey]')
    graph.append(audio_mix(music,frames)+frame_audio+'[musicBus]')
    graph.append('[musicBus][dialogueKey]sidechaincompress=threshold=0.003:ratio=16:attack=15:release=320:'
                 'knee=2:link=maximum:detection=rms,aformat=sample_fmts=fltp[duckedMusic]')
    return '[heardDialogue]', '[duckedMusic]'


def subtitle_ms(token):
    match = TIMESTAMP.fullmatch(token)
    h,m,s,ms = map(int,match.groups())
    return (((h*60)+m)*60+s)*1000+ms


def format_stamp(ms):
    h,rest=divmod(ms,3600000)
    m,rest=divmod(rest,60000)
    s,ms=divmod(rest,1000)
    return f'{h:02d}:{m:02d}:{s:02d},{ms:03d}'


def subtitle_cues(path,clip):
    source_start = round(clip.source_in*1000/FPS)
    source_end = round((clip.source_in+clip.frames)*1000/FPS)
    offset = round((clip.at-clip.source_in)*1000/FPS)
    for block in re.split(r'\n\s*\n',validate_srt(path).strip()):
        lines = block.splitlines()
        start,end = map(subtitle_ms,lines[1].split(' --> '))
        start,end = max(source_start,start),min(source_end,end)
        if start<end:
            yield start+offset,end+offset,'\n'.join(lines[2:])


def render_graph(timeline, paths, work, update):
    width,height = SIZES[timeline.profile]
    graph = [f'color=s={width}x{height}:r={FPS}:c=black,trim=end_frame={timeline.frames},settb=1/{FPS},setpts=N[base]']
    args, audios, captions, cache = [], [], [], {}
    composite = 'base'
    index = 0
    active = [track for track in timeline.tracks if track.enabled]
    if not any(track.role=='main' and track.clips for track in active):
        raise ValueError('主画面轨道必须包含至少一个已启用片段')
    ordered = sorted(active,key=lambda track:track.role!='main')
    for track in ordered:
        role = track.role
        for clip in sorted(track.clips,key=lambda item:item.at):
            update('inspecting',2)
            source = paths[clip.asset_id]
            suffix = source.suffix.lower()
            if role=='caption':
                captions.extend(subtitle_cues(source,clip))
                continue
            image = suffix in DEMUXERS
            if image:
                args += ['-protocol_whitelist','file,pipe','-f',DEMUXERS[suffix],'-i',str(source)]
                info = None
            else:
                args += ['-protocol_whitelist','file,pipe','-format_whitelist',MEDIA_FORMATS,'-i',str(source)]
                if source not in cache:
                    cache[source]=probe(source)
                info = cache[source]
            if role in VISUAL:
                w,h = show_dimensions(width,height,role)
                graph.append(video_filter(index,clip,source,image,info,w,h,role))
                position = 'x=W-w-24:y=24' if role=='overlay' else 'x=0:y=0'
                merged = f'composite{index}'
                graph.append(f'[{composite}][clipv{index}]overlay={position}:eof_action=pass:repeatlast=0[{merged}]')
                composite=merged
            elif role in AUDIO:
                graph.append(audio_filter(index,clip,info,track.volume))
                audios.append((role,f'[clipa{index}]'))
            index+=1
    if captions:
        captions.sort(key=lambda entry:entry[0])
        if any(a[1]>b[0] for a,b in zip(captions,captions[1:])):
            raise ValueError('字幕片段的输出提示时间重叠')
        chunks = [f'{i}\n{format_stamp(start)} --> {format_stamp(end)}\n{text}'
                  for i,(start,end,text) in enumerate(captions,1)]
        (work/'timeline.srt').write_text('\n\n'.join(chunks)+'\n',encoding='utf-8')
        graph.append(f'[{composite}]subtitles=filename=timeline.srt:charenc=UTF-8,format=yuv420p[outv]')
    else:
        graph.append(f'[{composite}]format=yuv420p[outv]')
    if audios:
        labels = [label for _,label in audios]
        if music_ducking_applies(timeline):
            dialogue,music = duck_music(graph,[label for role,label in audios if role=='dialogue'],
                                       [label for role,label in audios if role=='music'],timeline.frames)
            labels = [dialogue,music,*[label for role,label in audios if role=='sfx']]
        graph.append(audio_mix(labels,timeline.frames,limit=True)+'[outa]')
    return args,graph,bool(audios)


def timeline_render(task_id,attempt,parameters,snapshot,update):
    timeline = Timeline.model_validate(parameters['timeline'])
    signature = hashlib.sha256(json.dumps([ENGINE,parameters,snapshot],sort_keys=True).encode()).hexdigest()
    key = f'outputs/{task_id}/timeline.mp4'
    target = storage.resolve_key(key)
    published = target.parent/'timeline.json'
    paths = {}
    for asset_id,entry in snapshot['assets'].items():
        path = storage.resolve_key(entry['storage_key'])
        update('inspecting',0)
        if file_hash(path,lambda *_:update('inspecting',0))!=entry['sha256']:
            raise ValueError('固定素材哈希已变化')
        paths[asset_id]=path
    if target.exists():
        payload = json.loads(published.read_text(encoding='utf-8'))
        if payload['signature']!=signature or file_hash(target,lambda *_:update('validating',98))!=payload['sha256']:
            raise ValueError('已发布成片哈希或参数不一致')
        return payload
    work = storage.resolve_key(f'tmp/{task_id}/{attempt}')
    work.mkdir(parents=True,exist_ok=True)
    if shutil.disk_usage(work).free<256*1024**2:
        raise OSError('磁盘可用空间不足 256 MiB')
    args,graph,has_audio = render_graph(timeline,paths,work,update)
    (work/'graph.txt').write_text(';\n'.join(graph),encoding='utf-8')
    temporary = work/'timeline.mp4'
    argv = ['ffmpeg','-hide_banner','-nostdin','-n','-loglevel','warning','-xerror','-filter_complex_threads','2',
            '-progress','pipe:1',*args,'-filter_complex_script','graph.txt','-map','[outv]']
    if has_audio:
        argv += ['-map','[outa]','-c:a','aac','-b:a','192k']
    argv += ['-c:v','libx264','-threads','2','-preset','veryfast','-crf','19',
             '-fps_mode','cfr','-t',sec(timeline.frames),'-movflags','+faststart',str(temporary)]
    write_manifest(work/'command.json',argv)
    execute_ffmpeg(argv,work,timeline.frames/FPS,update,timeout=7200)
    update('validating',97)
    expected = {'size':SIZES[timeline.profile],'duration':timeline.frames/FPS,'audio':has_audio}
    output = validate_output(temporary,expected)
    video = stream_for(probe(temporary),'video')
    if int(video.get('nb_frames',0))!=timeline.frames or video['avg_frame_rate']!='24/1':
        raise ValueError('成片帧率/帧数与固定时间轴不符')
    verification = Commands(work,lambda *_:update('validating',98))
    verification.run(['ffmpeg','-nostdin','-v','error','-xerror','-protocol_whitelist','file,pipe',
        '-i',str(temporary),'-map','0:v:0','-map','0:a:0?','-f','null','-'],'timeline_decode',98,timeout=1800)
    payload = {**output,'storage_key':key,'signature':signature,'sha256':file_hash(temporary,lambda *_:update('validating',98)),
               'frame_rate':FPS,'frames':timeline.frames,'engine':ENGINE}
    if timeline.music_ducking:
        payload['music_ducking'] = {'status':'applied' if music_ducking_applies(timeline) else 'skipped',
                                    'preset':MUSIC_DUCKING_PRESET}
    update('publishing',99)
    target.parent.mkdir(parents=True,exist_ok=True)
    captions=work/'timeline.srt'
    if captions.is_file():
        caption_output=target.parent/'captions.srt'
        digest=file_hash(captions)
        if not caption_output.exists():
            os.link(captions,caption_output)
        elif file_hash(caption_output)!=digest:
            raise ValueError('已发布字幕与当前固定时间轴不符')
        payload.update(caption_storage_key=f'outputs/{task_id}/captions.srt',caption_sha256=digest)
    write_manifest(published,payload)
    os.link(temporary,target)
    temporary.unlink()
    return payload
