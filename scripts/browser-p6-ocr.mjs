import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { copyFile, readFile, writeFile } from 'node:fs/promises'
import { join } from 'node:path'
import { api, evidenceDir, openChrome, post, qaRoot, wait } from './chrome-qa.mjs'

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
const { contains, click, evaluate, setField, screenshot, errors, close }=await openChrome(19235)
try {
  await wait(()=>contains('服务就绪'),'production workbench ready')
  await click('智能解析')
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
