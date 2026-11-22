"""Run local technical QC on a published render and retain timestamped evidence."""
from hashlib import sha256
import math
import re
import subprocess

from . import storage
from .analysis_engine import Commands, parse_cues
from .generation import SIZES
from .guardian_audio import check_dialogue
from .guardian_balance import check_balance
from .media import probe
from .render import file_hash, validate_srt_text


RULE = 'ffmpeg-technical-v2'
BLACK = re.compile(r'black_start:([\d.eE+-]+)\s+black_end:([\d.eE+-]+)')
MARK = re.compile(r'\b(silence|freeze)_(start|end):\s*([\d.eE+-]+)')


def audio_measurements(log):
    _, marker, summary = log.rpartition('Summary:')
    if not marker:
        return {'status':'unavailable','integrated_lufs':None,'true_peak_dbtp':None}

    def value(pattern):
        match = re.search(pattern,summary,re.M)
        number = float(match[1]) if match else None
        return number if number is not None and math.isfinite(number) else None

    loudness = value(r'^\s+I:\s*([-\d.]+|[+-]?inf)\s+LUFS')
    peak = value(r'^\s+Peak:\s*([-\d.]+|[+-]?inf)\s+dBFS')
    if loudness is not None and loudness <= -70:
        loudness = None
    return {'status':'measured' if loudness is not None else 'below_gate_or_short',
            'integrated_lufs':loudness,'true_peak_dbtp':peak}


def check_captions(render, active, required, duration_ms, add, *, observed=None):
    output = render.output
    key = output.get('caption_storage_key')
    if not key and not active:
        if required:
            add('missing_subtitles','error','本批次要求字幕，成片没有实际输出字幕')
        return {'status':'absent'}
    try:
        path = storage.resolve_key(key or f'tmp/{render.id}/{render.attempt}/timeline.srt')
        with path.open('rb') as handle:
            contents = handle.read(2*1024**2+1)
    except FileNotFoundError:
        if key or required:
            add('missing_subtitles','error','成片字幕文件缺失')
        return {'status':'absent'}
    except (OSError,ValueError):
        add('subtitle_integrity','error','成片字幕文件无法安全读取')
        return {'status':'invalid'}
    digest = sha256(contents).hexdigest()
    expected = output.get('caption_sha256')
    if expected and digest != expected:
        add('subtitle_integrity','error','成片字幕与发布时的哈希不一致')
        return {'status':'invalid'}
    try:
        if len(contents) > 2*1024**2:
            raise ValueError('字幕超出 2 MiB')
        cues = parse_cues(validate_srt_text(contents.decode('utf-8-sig')))
    except ValueError:
        add('subtitle_format','error','成片 SRT 无法按 UTF-8 和有效时间行解析')
        return {'status':'invalid'}
    for index,cue in enumerate(cues,1):
        if cue['end_us'] > (duration_ms+1)*1000:
            add('subtitle_bounds','error',f'第 {index} 条成片字幕超出固定时间轴',
                min(cue['start_us']//1000,duration_ms-1),duration_ms)
            return {'status':'invalid'}
    for index,(previous,current) in enumerate(zip(cues,cues[1:]),2):
        if previous['end_us']>current['start_us']:
            add('subtitle_overlap','error',f'第 {index-1} 与第 {index} 条成片字幕时段重叠或顺序异常',
                current['start_us']//1000,min(previous['end_us'],current['end_us'])//1000)
            return {'status':'invalid'}
    if observed is not None:
        observed.extend(cues)
    return {'status':'verified' if expected else 'observed','sha256':digest,'cue_count':len(cues),
            'first_ms':cues[0]['start_us']//1000,'last_ms':cues[-1]['end_us']//1000}


def qa_output(render,policy,update,task_id,attempt,*,dialogue=None):
    output = render.output
    timeline = render.parameters['timeline']
    duration_ms = round(timeline['frames']*1000/timeline['frame_rate'])
    digest = output.get('sha256')
    issues = []

    def add(code,level,detail,start=None,end=None):
        values = {'code':code,'severity':level,'detail':detail,'start_ms':start,'end_ms':end}
        if start is not None:
            roles = {'main','overlay'}
            if code in ('silence','dialogue_background_masking'):
                roles = {'dialogue','music','sfx'}
            elif code.startswith('dialogue_'):
                roles = {'dialogue'}
            elif code.startswith('subtitle_'):
                roles = {'caption'}
            rate = timeline['frame_rate']
            values['clips'] = [clip['id'] for track in timeline['tracks'] if track['enabled'] and track['role'] in roles
                               for clip in track['clips'] if clip['at']*1000<(end if end is not None else duration_ms)*rate
                               and (clip['at']+clip['frames'])*1000>start*rate]
        issues.append(values)

    result = {'rule_version':RULE,'render_task_id':render.id,'output_sha256':digest,
              'duration_ms':duration_ms,'timeline_version_id':render.story_version_id,'issues':issues,
              'video':None,'audio':None,'captions':None}
    if 'music_ducking' in output:
        result['music_ducking'] = output['music_ducking']
    try:
        path = storage.resolve_key(output['storage_key'])
        update('qc_hash',3)
        if not digest or file_hash(path,lambda *_:update('qc_hash',3))!=digest:
            raise ValueError('成片和发布哈希不一致')
        report = probe(path)
    except (OSError,ValueError,KeyError,subprocess.SubprocessError):
        add('integrity','error','成片缺失、损坏或与已发布哈希不符')
        return result
    streams = report['streams']
    video = next((stream for stream in streams if stream['codec_type']=='video'),None)
    audio_streams = [stream for stream in streams if stream['codec_type']=='audio']
    has_audio = bool(audio_streams)
    active_roles = {track['role'] for track in timeline['tracks'] if track['enabled'] and track['clips']}
    if video:
        width,height = video.get('width'),video.get('height')
        frame_count = str(video.get('nb_frames',''))
        frame_rate = video.get('avg_frame_rate')
        result['video'] = {'width':width,'height':height,'frames':int(frame_count) if frame_count.isascii()
                           and frame_count.isdecimal() else None,'frame_rate':frame_rate}
    if (not video or video.get('codec_name')!='h264' or (width,height)!=SIZES[timeline['profile']]
        or frame_rate!=f"{timeline['frame_rate']}/1" or result['video']['frames']!=timeline['frames']):
        add('video_contract','error','视频编码、分辨率、帧率或帧数不符合固定时间轴')
    if (policy['require_audio'] or active_roles & {'dialogue','music','sfx'}) and not has_audio:
        add('missing_audio','error','本批次要求音轨，当前输出没有音轨')
    if has_audio and (len(audio_streams)!=1 or audio_streams[0].get('codec_name')!='aac'):
        add('audio_contract','error','成片应包含单条 AAC 混音轨')
    cues = [] if dialogue else None
    result['captions'] = check_captions(render,'caption' in active_roles,policy['require_subtitles'],duration_ms,add,
                                        observed=cues)
    if not video:
        return result
    work = storage.resolve_key(f'tmp/{task_id}/{attempt}')
    commands = Commands(work,update)
    filters = f"blackdetect=d={policy['black_ms']/1000}:pix_th=0.10,freezedetect=n=-60dB:d={policy['freeze_ms']/1000}"
    argv = ['ffmpeg','-nostdin','-v','info','-xerror','-filter_threads','2','-protocol_whitelist','file,pipe',
            '-i',str(path),'-map','0:v:0','-vf',filters]
    if has_audio:
        argv += ['-map','0:a:0','-af',f"silencedetect=n={policy['silence_db']}dB:d={policy['silence_ms']/1000},"
                 'ebur128=peak=true:framelog=verbose']
    argv += ['-f','null','-']
    try:
        _, log = commands.run(argv,'qc_decode',45,timeout=1800)
    except ValueError:
        add('decode_failed','error','完整音视频解码失败，技术日志已保存')
        return result
    content = log.read_text(encoding='utf-8',errors='replace')
    if has_audio:
        audio = audio_measurements(content)
        result['audio'] = audio
        loudness, peak = audio['integrated_lufs'], audio['true_peak_dbtp']
        floor, ceiling = policy.get('min_integrated_lufs'), policy.get('max_true_peak_dbtp')
        if floor is not None:
            if loudness is None:
                add('loudness_unmeasurable','warning','当前音轨未得到有效的整段响度')
            elif loudness < floor:
                add('low_loudness','warning',f'整段响度 {loudness:g} LUFS，低于所设下限 {floor:g} LUFS')
        if ceiling is not None:
            if audio['status']=='unavailable':
                add('peak_unmeasurable','warning','当前音轨未得到有效的真峰值测量摘要')
            elif peak is not None and peak > ceiling:
                add('high_true_peak','warning',f'真峰值 {peak:g} dBTP，高于所设上限 {ceiling:g} dBTP')

    def millis(text):
        return max(0,min(duration_ms,round(float(text)*1000)))

    for begin,end in BLACK.findall(content)[:100]:
        start,stop = millis(begin),millis(end)
        add('black_frames','warning','检测到连续黑场',start,stop)
    pending = {}
    for name,phase,position in MARK.findall(content):
        point = millis(position)
        if phase=='start':pending[name]=point
        elif name in pending and len(issues)<200:
            label = '检测到连续静音' if name=='silence' else '检测到连续冻结画面'
            add(name,'warning',label,pending.pop(name),point)
    for name,start in pending.items():
        add(name,'warning','异常持续到解码结尾',start,duration_ms)
    if dialogue:
        muted = any(track['enabled'] and track['role']=='dialogue' and track['clips'] and track['volume']==0
                    for track in timeline['tracks'])
        result['dialogue'] = check_dialogue(commands,path,duration_ms,dialogue,cues,has_audio,
                                            policy.get('dialogue_asr_language'),add,muted=muted)
        if has_audio and active_roles & {'music','sfx'} and not muted:
            result['dialogue']['balance'] = check_balance(commands,render,result['dialogue']['lines'],add)
    update('qc_report',97)
    return result
