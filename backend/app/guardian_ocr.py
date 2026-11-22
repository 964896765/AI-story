"""Compare Windows OCR observations with fixed screen-text terms."""
from pathlib import PurePosixPath

from .perception_ocr import recognize, recognizer
from .story_schemas import screen_text_key

RULE_VERSION = 'guardian-screen-text-v1'


def screen_text_findings(terms, samples):
    rows = [(sample['index'],[screen_text_key(text) for text in sample['lines']]) for sample in samples]
    findings = []
    for rule, code in [('required','required_not_seen'),('forbidden','forbidden_seen')]:
        for term in terms[rule]:
            key = screen_text_key(term)
            hits = [index for index,lines in rows if any(key in line for line in lines)]
            if rule=='required' and not hits:
                findings.append({'code':code,'term':term,'evidence_indices':[index for index,_ in rows]})
            if rule=='forbidden' and hits:
                findings.append({'code':code,'term':term,'evidence_indices':hits})
    return findings


def inspect_screen_text(commands, terms, assets, digest):
    ordered = sorted(assets.values(),key=lambda item:PurePosixPath(item['storage_key']).name)
    evidence = [{key:item[key] for key in ('index','time_ms','sha256')} for item in ordered]
    result = {'rule_version':RULE_VERSION,'output_sha256':digest,'contract':terms,'status':'unavailable',
              'adapter':None,'samples':[],'findings':[],'evidence':evidence}
    try:
        adapter = recognizer(terms['language'])
    except ValueError:
        return {**result,'reason':'language_unavailable'}
    result['adapter'] = adapter
    artifacts = [{'name':PurePosixPath(item['storage_key']).name,'time_us':item['time_ms']*1000} for item in ordered]
    try:
        recognized = recognize(commands,artifacts,adapter,stage='guardian_screen_ocr',progress=98)
    except (TimeoutError,ValueError,KeyError,TypeError):
        return {**result,'reason':'recognition_failed'}
    samples = [{**frame,'lines':(observed['lines'] or [observed['text']])[:64]}
               for frame,observed in zip(evidence,recognized,strict=True)]
    for sample in samples:
        sample['lines'] = [line[:500] for line in sample['lines']]
    findings = screen_text_findings(terms,samples)
    return {**result,'status':'review' if findings else 'matched','samples':samples,'findings':findings}
