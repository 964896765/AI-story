"""Run local technical QC on a published render and retain timestamped evidence."""
import re
import subprocess

from . import storage
from .analysis_engine import Commands
from .media import probe
from .render import file_hash


RULE = 'ffmpeg-technical-v1'
BLACK = re.compile(r'black_start:([\d.eE+-]+)\s+black_end:([\d.eE+-]+)')
MARK = re.compile(r'\b(silence|freeze)_(start|end):\s*([\d.eE+-]+)')


def qa_output(render,policy,update,task_id,attempt):
    output = render.output
    timeline = render.parameters['timeline']
    duration_ms = round(timeline['frames']*1000/timeline['frame_rate'])
    digest = output.get('sha256')
    issues = []

    def add(code,level,detail,start=None,end=None):
        values = {'code':code,'severity':level,'detail':detail,'start_ms':start,'end_ms':end}
        if start is not None:
            for track in timeline['tracks']:
                if track['role']=='main':
                    values['clips'] = [clip['id'] for clip in track['clips']
                        if clip['at']*1000//24<(end or duration_ms)
                        and (clip['at']+clip['frames'])*1000//24>start]
        issues.append(values)

    result = {'rule_version':RULE,'render_task_id':render.id,'output_sha256':digest,
              'duration_ms':duration_ms,'timeline_version_id':render.story_version_id,'issues':issues}
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
    has_audio = any(stream['codec_type']=='audio' for stream in streams)
    active_roles = {track['role'] for track in timeline['tracks'] if track['enabled'] and track['clips']}
    if not video or video['codec_name']!='h264' or int(video.get('nb_frames') or 0)!=timeline['frames']:
        add('video_contract','error','视频编码或帧数不符合固定时间轴')
    if policy['require_audio'] and not has_audio:
        add('missing_audio','error','本批次要求音轨，当前输出没有音轨')
    if policy['require_subtitles'] and 'caption' not in active_roles:
        add('missing_subtitles','error','本批次要求字幕，固定时间轴没有启用的字幕片段')
    if not video:
        return result
    work = storage.resolve_key(f'tmp/{task_id}/{attempt}')
    commands = Commands(work,update)
    filters = f"blackdetect=d={policy['black_ms']/1000}:pix_th=0.10,freezedetect=n=-60dB:d={policy['freeze_ms']/1000}"
    argv = ['ffmpeg','-nostdin','-v','info','-xerror','-filter_threads','2','-protocol_whitelist','file,pipe',
            '-i',str(path),'-map','0:v:0','-vf',filters]
    if has_audio:
        argv += ['-map','0:a:0','-af',f"silencedetect=n={policy['silence_db']}dB:d={policy['silence_ms']/1000}"]
    argv += ['-f','null','-']
    try:
        _, log = commands.run(argv,'qc_decode',45,timeout=1800)
    except ValueError:
        add('decode_failed','error','完整音视频解码失败，技术日志已保存')
        return result
    content = log.read_text(encoding='utf-8',errors='replace')

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
    update('qc_report',97)
    return result
