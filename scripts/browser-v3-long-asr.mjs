import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { readFile, writeFile } from 'node:fs/promises'
import { join, resolve } from 'node:path'
import { api, base, evidenceDir, openChrome, post, qaRoot, wait } from './chrome-qa.mjs'

await wait(async()=>{
  try { return (await api('/health')).ready && (await api('/queue')).workers.some(worker=>worker.online) }
  catch { return false }
},'local worker online')
const asr=(await api('/analysis/capabilities')).capabilities.find(item=>item.id==='asr')
assert(asr.available && asr.languages.includes('zh-CN'))
assert.equal(asr.max_seconds,1800)
const voice='Microsoft Huihui Desktop'
await writeFile(join(qaRoot,'dialogue-input.json'),JSON.stringify({lines:[
  {voice,rate:-1,text:'大家好，欢迎来到灯塔。今天的天气很好。'},
  {voice,rate:-1,text:'请准备出发，我们马上就到海边。'},
]}))
const shell=join(process.env.SystemRoot || 'C:/Windows','System32','WindowsPowerShell','v1.0','powershell.exe')
execFileSync(shell,['-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',resolve('scripts/synthesize_dialogue.ps1')],
  {cwd:qaRoot,timeout:25000})
const fixture='v3-09-long-asr.mkv'
execFileSync('ffmpeg',['-v','error','-f','lavfi','-i','color=white:s=160x120:r=2:d=193',
  '-i','line-001.wav','-i','line-002.wav','-filter_complex',
  '[1:a]asplit=2[early][repeat];[repeat]adelay=167500[bridge];[2:a]adelay=182000[late];[early][bridge][late]amix=inputs=3:normalize=0,apad=whole_dur=193[out]',
  '-map','0:v:0','-map','[out]','-t','193','-c:v','libx264','-threads','2','-c:a','pcm_s16le','-ar','16000',fixture],
  {cwd:qaRoot,timeout:25000})
const hash=bytes=>createHash('sha256').update(bytes).digest('hex')
const project=await post('/projects',{name:'V3 长音频分段转写验收'})
const route='/projects/'+project.id
const form=new FormData()
form.set('file',new Blob([await readFile(join(qaRoot,fixture))]),'自编长音频样片.mkv')
form.set('authorization','Windows 本机合成自编文字，仅用于隔离验收')
const asset=await api(route+'/assets',{method:'POST',body:form})
const { contains,click,evaluate,setField,screenshot,errors,close }=await openChrome(19237)
try {
  await wait(()=>contains('服务就绪'),'workbench ready')
  await setField('当前项目',project.id)
  await click('智能解析')
  await wait(()=>contains('自编长音频样片.mkv'),'long fixture visible')
  await wait(()=>evaluate(`(async () => {
    const probe=document.querySelector('.analysis-choices input[value=inspect]')
    const option=document.querySelector('.analysis-choices input[value=asr]')
    if (!probe || !option || option.disabled) return false
    if (probe.checked) probe.click()
    await Promise.resolve()
    if (!option.checked) option.click()
    return option.checked
  })()`),'transcription option enabled')
  await evaluate("document.querySelector('.analysis-options details').open=true")
  await setField('转写语言','zh-CN')
  await click('提交本地解析')
  const queue='/analysis'+route+'/assets/'+asset.id+'/tasks'
  let job
  await wait(async()=>{
    job=(await api(queue)).find(item=>item.parameters.operation==='asr')
    if (job?.status==='failed') throw new Error(job.error)
    return job?.status==='succeeded'
  },'Worker completes long speech',65000)
  const payload=await api('/analysis/tasks/'+job.id+'/result')
  const speech=payload.speech
  assert.equal(speech.chunk_count,2)
  assert.equal(speech.end_us,193000000)
  assert.deepEqual(speech.chunks.map(chunk=>[chunk.start_us,chunk.end_us]),[[0,175000000],[165000000,193000000]])
  const [track]=payload.subtitle_tracks
  const lighthouse=track.cues.filter(cue=>cue.text.includes('灯塔'))
  assert.equal(lighthouse.length,2)
  assert(lighthouse.some(cue=>cue.start_us<10000000))
  assert(lighthouse.some(cue=>cue.start_us>167000000 && cue.start_us<170000000 && cue.end_us>170000000))
  const late=track.cues.find(cue=>cue.start_us>180000000 && cue.text.includes('我们马上'))
  assert(late)
  assert(track.cues.every((cue,index)=>index===0 || track.cues[index-1].end_us<=cue.start_us))
  await wait(()=>contains('2 段转写已合并'),'merge result visible')
  await click('试听音轨')
  await wait(()=>evaluate("document.querySelector('.analysis-monitor audio')?.duration>190"),'continuous audition has full duration')
  const seam=speech.merge_boundaries[0]
  await evaluate("document.querySelector('.speech-seam button').click()")
  await wait(()=>evaluate(`Math.abs(document.querySelector('.analysis-monitor audio').currentTime-${seam.merge_us/1000000})<.035`),
    'merge boundary seeks to source time')
  await evaluate("Array.from(document.querySelectorAll('.cue-list button')).find(button=>button.textContent.includes('我们马上')).click()")
  await wait(()=>evaluate(`Math.abs(document.querySelector('.analysis-monitor audio').currentTime-${late.start_us/1000000})<.035`),'late text seeks to source time')
  const corrected='请准备出发，我们马上就到海边。'
  await setField('字幕文本',corrected)
  await evaluate("document.querySelector('.speech-chunks').open=true")
  await evaluate("document.querySelector('.hard-subtitle-summary').scrollIntoView({block:'center'})")
  await screenshot('v3-09-long-asr.png')
  await click('保存字幕素材')
  await wait(()=>contains('字幕素材 v1 已保存'),'merged phrases saved to one SRT')
  const [version]=await api(queue+'/'+job.id+'/subtitle-tracks/'+track.stream_index+'/revisions')
  assert.equal(version.media_info.speech.chunk_count,2)
  const bytes=Buffer.from(await (await fetch(base+'/api/assets/'+version.id+'/media')).arrayBuffer())
  assert.equal(hash(bytes),version.sha256)
  assert(bytes.toString().includes('00:03:') && bytes.toString().includes(corrected))
  assert.deepEqual(errors,[])
  await writeFile(join(evidenceDir,'v3-long-asr-browser-acceptance.json'),JSON.stringify({
    checked_at:new Date().toISOString(),source_duration_us:speech.end_us,chunks:speech.chunks,merge_boundaries:speech.merge_boundaries,
    captions:track.cues,seam_playback_us:seam.merge_us,late_playback_us:late.start_us,corrected_late_text:corrected,
    merged_subtitle_sha256:version.sha256,paid_model_calls:0,js_errors:errors,
  },null,2)+'\n')
  console.log('V3 long ASR browser: 193 seconds, overlapping speech, continuous audition and one reviewed SRT verified.')
} catch(error) {
  console.error(await evaluate('document.body.innerText.slice(-6500)'))
  throw error
} finally { await close() }
