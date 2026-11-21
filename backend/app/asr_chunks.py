"""Bound audio sent to Windows dictation and join cues in the source time base."""
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from unicodedata import normalize
import wave

from .perception_asr import transcribe
from .render import write_manifest

CORE_US = 170_000_000
PADDING_US = 5_000_000
CHUNK_LIMIT_US = CORE_US + 2*PADDING_US
PIPELINE = 'overlapping-speech-v1'
MAX_CHECKPOINT_BYTES = 4*1024**2


@dataclass(frozen=True)
class SpeechChunk:
    start_us: int
    end_us: int
    core_us: int


def plan_chunks(duration_us):
    if duration_us <= CHUNK_LIMIT_US:
        return [SpeechChunk(0, duration_us, 0)]
    return [SpeechChunk(max(0, core-PADDING_US), min(duration_us, core+CORE_US+PADDING_US), core)
            for core in range(0, duration_us, CORE_US)]


def common_pause(left, right, start, end, target):
    intervals = sorted((max(start, cue['start_us']), min(end, cue['end_us']))
                       for cue in (*left, *right) if cue['end_us'] > start and cue['start_us'] < end)
    candidates = []
    cursor = start
    for low, high in [*intervals, (end,end)]:
        if low - cursor >= 200_000:
            candidates.append(min(max(target,cursor),low))
        cursor = max(cursor,high)
    return min(candidates, key=lambda point: abs(target-point)) if candidates else None


def merge_chunks(plan, batches, source_start):
    cues = list(batches[0])
    seams = []
    for earlier, later, next_cues in zip(plan,plan[1:],batches[1:]):
        target = source_start+later.core_us
        cut = common_pause(cues, next_cues, source_start+later.start_us, source_start+earlier.end_us, target)
        review = cut is None
        cut = target if review else cut
        cues = [cue for cue in cues if cue['start_us'] < cut]
        for cue in next_cues:
            if cue['end_us'] <= cut:
                continue
            if cues and cue['start_us'] < cues[-1]['end_us']:
                previous = cues[-1]
                if (cue['end_us'] <= previous['end_us'] or
                        normalize('NFKC',cue['text']) == normalize('NFKC',previous['text'])):
                    continue
                cue = {**cue, 'start_us': previous['end_us']}
            cues.append(cue)
        seams.append({'boundary_us':target, 'merge_us':cut, 'needs_review':review})
    return cues, seams


def checksum(data):
    return hashlib.sha256(json.dumps(data,ensure_ascii=False,sort_keys=True).encode('utf-8')).hexdigest()


@dataclass(frozen=True)
class SpeechCheckpoint:
    directory: Path
    signature: str

    def read(self, number, window):
        try:
            with (self.directory/f'{number:03d}.json').open('rb') as handle:
                raw = handle.read(MAX_CHECKPOINT_BYTES+1)
            if len(raw) > MAX_CHECKPOINT_BYTES:
                return None
            record = json.loads(raw)
            data = record['data']
            if (data['signature'] == self.signature and data['window'] == window and
                    isinstance(data['cues'], list) and record['sha256'] == checksum(data)):
                return data['cues']
        except (OSError, ValueError, TypeError, KeyError):
            pass
        return None

    def write(self, number, window, cues):
        data = {'signature':self.signature,'window':window,'cues':cues}
        self.directory.mkdir(parents=True,exist_ok=True)
        write_manifest(self.directory/f'{number:03d}.json',{'data':data,'sha256':checksum(data)})


def recognize_chunks(commands, audio, adapter, source_start, duration_us, checkpoint):
    plan = plan_chunks(duration_us)
    if len(plan) == 1:
        return transcribe(commands,audio,adapter,source_start,duration_us), {}

    batches, reused = [], 0
    with wave.open(str(audio),'rb') as source:
        rate = source.getframerate()
        for index, chunk in enumerate(plan):
            progress = 40 + 50*index/len(plan)
            commands.update('analysis_asr_chunk', progress)
            window = [source_start+chunk.start_us, source_start+chunk.end_us]
            cues = checkpoint.read(index,window) if checkpoint else None
            if cues is None:
                start_frame = chunk.start_us*rate//1_000_000
                end_frame = min(source.getnframes(),(chunk.end_us*rate+999_999)//1_000_000)
                partial = commands.work / f'asr-chunk-{index:03d}.wav'
                try:
                    source.setpos(start_frame)
                    with wave.open(str(partial),'wb') as handle:
                        handle.setparams(source.getparams())
                        handle.writeframes(source.readframes(end_frame-start_frame))
                    cues = transcribe(commands,partial,adapter,window[0],chunk.end_us-chunk.start_us,progress)
                    if checkpoint:
                        checkpoint.write(index,window,cues)
                finally:
                    partial.unlink(missing_ok=True)
            else:
                reused += 1
            batches.append(cues)
    cues, seams = merge_chunks(plan,batches,source_start)
    if len(cues) > 10_000:
        raise ValueError('合并后的字幕超过 10000 条，请缩短转写范围')
    return cues, {
        'chunk_count':len(plan), 'reused_chunks':reused, 'merge_boundaries':seams,
        'chunks':[{'start_us':source_start+chunk.start_us,'end_us':source_start+chunk.end_us,'cue_count':len(rows)}
                  for chunk,rows in zip(plan,batches)],
    }
