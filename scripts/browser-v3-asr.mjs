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
const speech=(await api('/analysis/capabilities')).capabilities.find(item=>item.id==='asr')
assert(speech.available && speech.languages.includes('zh-CN'),'Mandarin desktop speech recognition required')
const voice='Microsoft Huihui Desktop'
await writeFile(join(qaRoot,'dialogue-input.json'),JSON.stringify({lines:[
  {voice,rate:-1,text:'大家好，欢迎来到灯塔。今天的天气很好。'},
  {voice,rate:-1,text:'请准备出发，我们马上就到海边。'},
]}))
const shell=join(process.env.SystemRoot || 'C:/Windows','System32','WindowsPowerShell','v1.0','powershell.exe')
execFileSync(shell,['-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',resolve('scripts/synthesize_dialogue.ps1')],
  {cwd:qaRoot,timeout:25000})
const media='v3-08-asr-sample.mkv'
execFileSync('ffmpeg',['-v','error','-f','lavfi','-i','color=white:s=320x240:r=24:d=16',
  '-f','lavfi','-i','anullsrc=r=16000:cl=mono:d=16','-i','line-001.wav','-i','line-002.wav',
  '-filter_complex','[2:a]apad=pad_dur=1[first];[first][3:a]concat=n=2:v=0:a=1,adelay=2500,apad=whole_dur=16[out]',
  '-map','0:v:0','-map','1:a:0','-map','[out]','-t','16','-c:v','libx264','-threads','2','-c:a','pcm_s16le',media],
  {cwd:qaRoot,timeout:25000})
const digest=bytes=>createHash('sha256').update(bytes).digest('hex')
const project=await post('/projects',{name:'V3 本机转写验收'})
const route='/projects/'+project.id
const original=await readFile(join(qaRoot,media))
const form=new FormData()
form.set('file',new Blob([original]),'自编双轨语音样片.mkv')
form.set('authorization','自编文本，由 Windows 本机音色用于隔离验收')
const asset=await api(route+'/assets',{method:'POST',body:form})
assert.equal(asset.sha256,digest(original))

const {command,contains,click,evaluate,setField,screenshot,errors,close}=await openChrome(19236)
try {
  await wait(()=>contains('服务就绪'),'production build ready')
  await setField('当前项目',project.id)
  await click('智能解析')
  await wait(()=>contains('自编双轨语音样片.mkv'),'sample selected')
  await click('提交本地解析')
  await wait(()=>contains('完整媒体元数据'),'stream inventory ready')
  await wait(()=>evaluate(`(async () => {
    const inspect=document.querySelector('.analysis-choices input[value=inspect]')
    const asr=document.querySelector('.analysis-choices input[value=asr]')
    if (!inspect || !asr || asr.disabled) return false
    if (inspect.checked) inspect.click()
    await Promise.resolve()
    if (!asr.checked) asr.click()
    return asr.checked
  })()`),'local transcription selectable')
  await wait(()=>evaluate(`(() => {
    const settings=document.querySelector('.analysis-options details')
    if (!settings) return false
    return settings.open=true
  })()`),'transcription options load')
  await setField('本机语音转写源流','2')
  await setField('转写语言','zh-CN')
  await setField('转写开始（秒）','2')
  await setField('转写结束（秒）','15')
  await click('提交本地解析')
  const queue='/analysis'+route+'/assets/'+asset.id+'/tasks'
  let job
  await wait(async()=>{
    job=(await api(queue)).find(item=>item.parameters.operation==='asr')
    if (job?.status==='failed') throw new Error(job.error)
    return job?.status==='succeeded'
  },'Worker performs real local dictation',45000)
  const result=await api('/analysis/tasks/'+job.id+'/result')
  const [track]=result.subtitle_tracks
  assert.equal(track.stream_index,2)
  assert(track.cues[0].start_us > 2400000 && track.cues[0].start_us < 3200000)
  assert(track.cues.some(cue=>cue.text.includes('天气很好')))
  assert(track.cues.some(cue=>cue.text.includes('我们马上')))
  await wait(()=>contains('待校对的语音转写'),'visible recognized transcript')
  await click('试听音轨')
  await wait(()=>evaluate("document.querySelector('.analysis-monitor audio')?.readyState>=1"),'selected speech WAV playable')
  await evaluate("document.querySelector('.cue-list button').click()")
  const expectedOffset=(track.cues[0].start_us-result.speech.start_us)/1000000
  await wait(()=>evaluate(`Math.abs(document.querySelector('.analysis-monitor audio').currentTime-${expectedOffset})<.025`),
    'cue seeks into audition relative to source range')
  const at=await evaluate("document.querySelector('.analysis-link').href")
  const link=new URL(at)
  assert.equal(link.searchParams.get('at'),String(track.cues[0].start_us))
  assert.equal(link.searchParams.get('preview'),job.id)
  await command('Page.navigate',{url:at})
  await wait(()=>evaluate(`document.querySelector('.analysis-monitor audio')?.readyState>=1 &&
    Math.abs(document.querySelector('.analysis-monitor audio').currentTime-${expectedOffset})<.025`),'audition survives deep link')

  await wait(()=>evaluate("document.querySelector('.subtitle-draft fieldset')?.disabled===false"),'caption review editor ready')
  await setField('字幕文本','大家好，欢迎来到灯塔。')
  await click('保存字幕素材')
  await wait(()=>contains('字幕素材 v1 已保存'),'reviewed version saved')
  const revisionRoute=queue+'/'+job.id+'/subtitle-tracks/2/revisions'
  const [version]=await api(revisionRoute)
  assert.equal(version.media_info.subtitle_origin,'asr_estimated')
  assert.equal(version.media_info.speech.stream_index,2)
  assert.equal(version.media_info.derived_from_asset,asset.id)
  const raw=Buffer.from(await (await fetch(base+'/api/assets/'+version.id+'/media')).arrayBuffer())
  assert(raw.toString().includes('大家好，欢迎来到灯塔。'))
  assert.equal(digest(raw),version.sha256)
  await evaluate("document.querySelector('.subtitle-draft').scrollIntoView({block:'center'})")
  await screenshot('v3-08-asr-review.png')
  await click('带入剪辑')
  await wait(()=>evaluate(`document.querySelector('.input-clips input:checked')?.value==='${asset.id}' &&
    [...document.querySelectorAll('select')].some(field=>field.value==='${version.id}')`),'fixed subtitle and source handed to editor')
  await click('提交 1 项剪辑任务')
  let render
  await wait(async()=>{
    render=(await api(route+'/tasks')).find(task=>task.kind==='render')
    if (render?.status==='failed') throw new Error(render.error)
    return render?.status==='succeeded'
  },'verified video rendered from reviewed transcript',30000)
  assert.equal(render.input_snapshot.subtitle.sha256,version.sha256)
  const output=await fetch(base+'/api/tasks/'+render.id+'/output',{headers:{Range:'bytes=0-99'}})
  assert.equal(output.status,206)
  assert.equal((await output.arrayBuffer()).byteLength,100)
  const untouched=await fetch(base+'/api/assets/'+asset.id+'/media')
  assert.equal(digest(Buffer.from(await untouched.arrayBuffer())),asset.sha256)
  assert.deepEqual(errors,[])
  await writeFile(join(evidenceDir,'v3-asr-browser-acceptance.json'),JSON.stringify({
    checked_at:new Date().toISOString(),engine:speech.engine,language:result.speech.language,selected_audio_stream:track.stream_index,
    source_range_us:[result.speech.start_us,result.speech.end_us],recognized_cues:track.cues,
    audition_local_seek_seconds:expectedOffset,deep_link_restored:true,reviewed_subtitle_sha256:version.sha256,
    original_sha256:asset.sha256,render_verified:true,output_range_http:output.status,paid_model_calls:0,js_errors:errors,
  },null,2)+'\n')
  console.log('V3 ASR browser: real Mandarin dictation, selected audio audition, SRT adoption and Worker render passed.')
} catch (error) {
  console.error(await evaluate('document.body.innerText.slice(-6500)'))
  throw error
} finally { await close() }
