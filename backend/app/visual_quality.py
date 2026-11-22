"""Deterministic visual checks on locally decoded Guardian candidate frames."""

RULE_VERSION = 'guardian-visual-luma-v1'
WIDTH, HEIGHT = 96, 54
FRAME_BYTES = WIDTH * HEIGHT
MAX_FINDINGS = 8
BLACK_LEVEL = 12
BLACK_COVERAGE = 0.99
MIN_BLACK_FRAMES = 6
MIN_STILL_FRAMES = 18
STILL_DELTA = 0.35


def finding(code, severity, start, stop):
    return {
        'code': code, 'severity': severity,
        'start_ms': round(start * 1000 / 24), 'end_ms': round(stop * 1000 / 24),
        'frame_number': (start + stop - 1) // 2,
    }


def inspect_frames(raw, frame_count, digest):
    if frame_count < 1 or len(raw) != frame_count * FRAME_BYTES:
        raise ValueError('候选逐帧解码数量与固定镜头帧数不符')
    frames = memoryview(raw)
    black_start = None
    black_count = 0
    black = []
    still = []
    anchor, anchor_index = None, 0
    for index in range(frame_count):
        pixels = frames[index * FRAME_BYTES:(index + 1) * FRAME_BYTES]
        almost_black = sum(value <= BLACK_LEVEL for value in pixels) >= FRAME_BYTES * BLACK_COVERAGE
        if almost_black:
            black_count += 1
            if black_start is None:
                black_start = index
        elif black_start is not None:
            if index - black_start >= MIN_BLACK_FRAMES:
                black.append((black_start, index))
            black_start = None
        if anchor is None or sum(abs(a - b) for a, b in zip(anchor, pixels)) > FRAME_BYTES * STILL_DELTA:
            if index - anchor_index >= MIN_STILL_FRAMES:
                still.append((anchor_index, index))
            anchor, anchor_index = pixels, index
    if black_start is not None and frame_count - black_start >= MIN_BLACK_FRAMES:
        black.append((black_start, frame_count))
    if frame_count - anchor_index >= MIN_STILL_FRAMES:
        still.append((anchor_index, frame_count))

    if black_count == frame_count:
        findings = [finding('black_output', 'error', 0, frame_count)]
    else:
        findings = [finding('black_segment', 'warning', start, stop) for start, stop in black]
        findings.extend(finding('low_motion', 'warning', start, stop) for start, stop in still
                        if not any(start >= begin and stop <= end for begin, end in black))
    findings.sort(key=lambda item: (item['start_ms'], item['code']))
    return {'rule_version': RULE_VERSION, 'output_sha256': digest, 'checked_frames': frame_count,
            'black_frames': black_count,
            'status': 'blocked' if black_count == frame_count else 'review' if findings else 'clear',
            'findings': findings[:MAX_FINDINGS], 'omitted_findings': max(0, len(findings) - MAX_FINDINGS)}


def inspect_video(commands, path, frame_count, digest):
    raw, _ = commands.run(
        ['ffmpeg', '-v', 'error', '-nostdin', '-xerror', '-filter_threads', '2',
         '-protocol_whitelist', 'file,pipe', '-i', str(path), '-map', '0:v:0',
         '-vf', f'scale={WIDTH}:{HEIGHT}:flags=area:out_range=full,format=gray',
         '-fps_mode', 'passthrough', '-frames:v', str(frame_count + 1), '-threads', '1', '-f', 'rawvideo', '-'],
        'guardian_visual_check', 98, timeout=45)
    try:
        return inspect_frames(raw.read_bytes(), frame_count, digest)
    finally:
        raw.unlink(missing_ok=True)
