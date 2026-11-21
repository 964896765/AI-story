import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { copyFile, readFile, writeFile } from 'node:fs/promises'
import { join } from 'node:path'
import { api, base, evidenceDir, openChrome, post, qaRoot, wait } from './chrome-qa.mjs'

await wait(async () => {
  try { return (await api('/health')).ready && (await api('/queue')).workers.some(node=>node.online) }
  catch { return false }
}, 'isolated online Worker')
const capability=(await api('/analysis/capabilities')).capabilities.find(item=>item.id==='ocr')
assert(capability.available && capability.languages.includes('zh-Hans-CN'), 'Installed simplified-Chinese OCR is required')
await copyFile(join(process.env.SystemRoot || 'C:/Windows','Fonts','simhei.ttf'),join(qaRoot,'ocr-fixture-font.ttf'))
const clip='ocr-sample.mp4'
execFileSync('ffmpeg',['-v','error','-f','lavfi','-i','color=white:s=960x540:r=24:d=1',
  '-f','lavfi','-i','color=black:s=960x540:r=24:d=1','-filter_complex',
  "[0:v]drawtext=fontfile=ocr-fixture-font.ttf:text='灯塔坐标':fontsize=105:fontcolor=black:x=(w-tw)/2:y=(h-th)/2[a];[a][1:v]concat=n=2:v=1:a=0[v]",
  '-map','[v]','-c:v','libx264','-threads','2',clip],{cwd:qaRoot,timeout:30000})
const original=await readFile(join(qaRoot,clip))
const project=await post('/projects',{name:'P6-B 本机 OCR 浏览器验收'})
const root='/projects/'+project.id
const form=new FormData()
form.set('file',new Blob([original]),'自制灯塔文字.mp4')
form.set('authorization','独立测试中用 FFmpeg 生成的自编文字及画面')
const asset=await api(root+'/assets',{method:'POST',body:form})
assert.equal(asset.sha256,createHash('sha256').update(original).digest('hex'))
const timedFilters = [['画面水印', '20', 0, 3], ['灯塔坐标', 'h-th-32', .5, 1.25], ['日出时间', 'h-th-32', 1.75, 2.5]]
  .map(([text, y, start, end])=>`drawtext=fontfile=ocr-fixture-font.ttf:text='${text}':fontsize=92:fontcolor=black:x=(w-tw)/2:y=${y}:enable='gte(t,${start})*lt(t,${end})'`)
  .join(',')
async function uploadFixture(file, name, filters) {
  execFileSync('ffmpeg',['-v','error','-f','lavfi','-i','color=white:s=960x540:r=24:d=3',
    ...filters,'-c:v','libx264','-threads','2',file],{cwd:qaRoot,timeout:30000})
  const upload=new FormData()
  upload.set('file',new Blob([await readFile(join(qaRoot,file))]),name)
  upload.set('authorization','FFmpeg 本机自制验收素材')
  return api(root+'/assets',{method:'POST',body:upload})
}
const timed=await uploadFixture('hard-timed.mp4','自制硬字幕.mp4',['-vf',timedFilters])
const clean=await uploadFixture('clean.mp4','无旧字幕底片.mp4',[])
const { contains, click, evaluate, setField, screenshot, errors, close }=await openChrome(19235)
try {
  await wait(()=>contains('服务就绪'),'production workbench ready')
  await click('智能解析')
  await wait(()=>contains('自制灯塔文字.mp4'),'original OCR sample in list')
  await setField('解析素材',asset.id)
  await wait(()=>evaluate(`(async () => {
    const box = document.querySelector('.analysis-choices input[value=ocr]')
    if (!box || box.disabled) return false
    document.querySelector('.analysis-choices input[value=inspect]').click()
    await Promise.resolve()
    document.querySelector('.analysis-choices input[value=scenes]').click()
    await Promise.resolve()
    box.click()
    return true
  })()`),'installed OCR enabled')
  await evaluate("document.querySelector('.analysis-options details').open = true")
  await setField('OCR 语言','zh-Hans-CN')
  await setField('OCR 采样间隔（秒）','1')
  await click('提交本地解析')
  await wait(()=>contains('快照证据 · 2 项'),'cut and OCR results synchronized',35000)
  await click('本机画面文字识别')
  await wait(()=>contains('2 个采样帧'),'screen text result displayed')
  await evaluate(`Array.from(document.querySelectorAll('summary')).find(node=>node.textContent.startsWith('OCR 文字采样')).click()`)
  await click('以此帧创建人工校对')
  await evaluate(`Array.from(document.querySelectorAll('summary')).find(node=>node.textContent.startsWith('人工时间证据')).click()`)
  await setField('人工描述','灯塔坐标（已按画面校正）')
  await setField('终点（微秒）','1000000')
  await setField('审核说明','人工查看自制画面与时间范围')
  await click('保存审核快照')
  await wait(()=>contains('已保存审核快照 v1'),'saved raw observation and human evidence')
  await evaluate(`(() => { const stored=Array.from(document.querySelectorAll('summary')).find(node=>node.textContent.startsWith('已保存的 OCR 采样'));
    stored.click(); stored.scrollIntoView({block:'center'}); })()`)
  await screenshot('p6-ocr-review.png')
  const revisionRoot='/analysis/assets/'+asset.id+'/revisions'
  const [latest]=await api(revisionRoot)
  const {payload}=await api('/analysis/revisions/'+latest.id)
  assert.equal(payload.ocr_samples.length,1)
  assert.equal(payload.ocr_samples[0].text.replace(/\s/g,''),'灯塔坐标')
  assert.deepEqual(payload.ocr_samples[0].shots,[1])
  assert.equal(payload.ocr_samples[0].start_us,0)
  assert.deepEqual(payload.evidence[0].shots,[1])
  assert.equal(payload.evidence[0].origin,'human')
  assert.equal(payload.evidence[0].text,'灯塔坐标（已按画面校正）')
  await setField('采纳说明','批准使用人工核对的自编文字')
  await setField('审核稿标题','已复核灯塔坐标')
  await click('载入人工校对的画面文字')
  await click('保存 P4 剧本并打开 P5 改编')
  await wait(()=>contains('固定原稿 已复核灯塔坐标'),'confirmed text adopted as fixed script')
  const entities=await api(root+'/story/entities')
  const version=await api('/story/versions/'+entities.items.find(item=>item.kind==='script').version_id)
  assert.equal(version.content.body,payload.evidence[0].text)
  assert.equal(version.provenance.analysis_revision_id,latest.id)

  await click('智能解析')
  await wait(()=>contains('自制硬字幕.mp4'),'timed sample in list')
  await setField('解析素材',timed.id)
  await wait(()=>evaluate(`(async () => {
    const inspect = document.querySelector('.analysis-choices input[value=inspect]')
    const hard = document.querySelector('.analysis-choices input[value=hard_subtitles]')
    if (!inspect || !hard || hard.disabled) return false
    if (inspect.checked) inspect.click()
    await Promise.resolve()
    if (!hard.checked) hard.click()
    return hard.checked
  })()`),'hard subtitle operation enabled')
  await wait(()=>evaluate(`(() => {
    const settings = document.querySelector('.analysis-options details')
    if (!settings) return false
    return settings.open = true
  })()`),'hard subtitle options visible')
  await setField('OCR 语言','zh-Hans-CN')
  await setField('硬字幕开始（秒）','0.25')
  await setField('硬字幕结束（秒）','2.75')
  await setField('硬字幕采样间隔（秒）','0.25')
  await click('提交本地解析')
  await wait(()=>contains('OCR 估算时序'),'Worker timed captions visible',35000)
  const taskPath='/analysis'+root+'/assets/'+timed.id+'/tasks'
  const [hardTask]=await api(taskPath)
  const hard=await api('/analysis/tasks/'+hardTask.id+'/result')
  const [track]=hard.subtitle_tracks
  const expected=[[500000,1250000],[1750000,2500000]]
  assert.deepEqual(track.cues.map(c=>[c.start_us,c.end_us]),expected)
  assert.deepEqual(track.cues.map(c=>c.text.replace(/\s/g,'')),['灯塔坐标','日出时间'])
  assert.deepEqual(track.cues.map(c=>c.sample_count),[3,3])
  await evaluate("document.querySelector('.cue-list button').click()")
  await wait(()=>evaluate("document.querySelector('.caption-evidence img')?.naturalWidth > 0"),'cropped OCR source evidence loaded')
  await wait(()=>evaluate("Math.abs(document.querySelector('video').currentTime-.5)<.04"),'OCR cue seeks to source frame')
  await setField('字幕文本','灯塔坐标（已校对）')
  await click('保存字幕素材')
  await wait(()=>contains('字幕素材 v1 已保存'),'reviewed SRT persisted')
  const [subtitle]=await api(taskPath+'/'+hardTask.id+'/subtitle-tracks/'+track.stream_index+'/revisions')
  assert.equal(subtitle.media_info.subtitle_origin,'ocr_estimated')
  assert.equal(subtitle.media_info.derived_from_asset,timed.id)
  const downloaded=Buffer.from(await (await fetch(base+'/api/assets/'+subtitle.id+'/media')).arrayBuffer())
  assert(downloaded.toString().includes('00:00:00,500 --> 00:00:01,250\n灯塔坐标（已校对）'))
  assert.equal(createHash('sha256').update(downloaded).digest('hex'),subtitle.sha256)
  await evaluate("document.querySelector('.hard-subtitle-summary').scrollIntoView({block:'start'})")
  await screenshot('v3-06-hard-subtitles.png')
  await click('带入剪辑')
  await wait(()=>evaluate(`[...document.querySelectorAll('select')].some(field=>field.value==='${subtitle.id}')`),'specific OCR subtitle preselected')
  assert.equal(await evaluate("document.querySelectorAll('.input-clips input:checked').length"),0)
  await wait(()=>evaluate(`!!document.querySelector('.input-clips input[value="${clean.id}"]')`),'clean source listed')
  await evaluate(`document.querySelector('.input-clips input[value="${clean.id}"]').click()`)
  await click('提交 1 项剪辑任务')
  let render
  await wait(async ()=>{
    render=(await api(root+'/tasks')).find(task=>task.kind==='render')
    if (render?.status==='failed') throw new Error(render.error)
    return render?.status==='succeeded'
  },'clean picture successfully rendered with reviewed SRT',35000)
  assert.equal(render.asset_id,clean.id)
  assert.equal(render.input_snapshot.subtitle.sha256,subtitle.sha256)
  const output=await fetch(base+'/api/tasks/'+render.id+'/output')
  assert.equal(output.status,200)
  const outputFile=join(qaRoot,'hard-reviewed.mp4')
  await writeFile(outputFile,Buffer.from(await output.arrayBuffer()))
  const pixel = seconds => execFileSync('ffmpeg',['-v','error','-ss',seconds,'-i',outputFile,'-frames:v','1',
    '-vf','crop=960:150:0:390,format=gray','-threads','1','-f','rawvideo','pipe:1'],{timeout:20000})
  const dark = seconds => pixel(seconds).filter(value=>value<165).length
  const rendered=[dark('0.25'),dark('0.75'),dark('1.5'),dark('2'),dark('2.75')]
  assert(rendered[1]>20 && rendered[3]>20)
  assert.equal(rendered[0]+rendered[2]+rendered[4],0)
  const unchanged=Buffer.from(await (await fetch(base+'/api/assets/'+timed.id+'/media')).arrayBuffer())
  assert.equal(createHash('sha256').update(unchanged).digest('hex'),timed.sha256)
  await writeFile(join(evidenceDir,'v3-06-hard-subtitles.json'),JSON.stringify({
    checked_at:new Date().toISOString(),engine:capability.engine,language:capability.languages[0],
    expected_us:expected,recognized_us:track.cues.map(c=>[c.start_us,c.end_us]),sampled_frames:hard.ocr.frames.length,
    reviewed_subtitle_sha256:subtitle.sha256,immutable_source_sha256:timed.sha256,
    rendered_dark_pixels:rendered,clean_source_rendered:true,paid_model_calls:0,js_errors:errors,
  },null,2)+'\n')
  assert.deepEqual(errors,[])
  await writeFile(join(evidenceDir,'p6-ocr-browser-acceptance.json'),JSON.stringify({
    checked_at:new Date().toISOString(), browser:'Installed Chrome headless', engine:capability.engine,
    language:'zh-Hans-CN', raw_text:payload.ocr_samples[0].text, reviewed_text:version.content.body,
    sampled_time_us:0, aligned_shots:[1], verified_script_reference:true,
    original_sha256:asset.sha256, paid_model_calls:0, js_errors:errors,
  },null,2)+'\n')
  console.log('P6-B OCR browser: real burned-in Chinese text, frame timestamp, shot alignment, correction and P5 handoff passed.')
} catch (error) {
  console.error(await evaluate('document.body.innerText.slice(-6500)'))
  throw error
} finally { await close() }
