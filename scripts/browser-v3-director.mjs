import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { readFile, writeFile } from 'node:fs/promises'
import { join } from 'node:path'
import { api, base, evidenceDir, openChrome, post, qaRoot, wait } from './chrome-qa.mjs'

await wait(async () => {
  try { return (await api('/health')).ready && (await api('/queue')).workers.some(worker => worker.online) }
  catch { return false }
}, 'local API and Worker')
const model = await api('/text/status')
assert.equal(model.live_authorized, false)
assert.equal(model.default_live_budget_micros, 0)
const project = await post('/projects', {name:'总导演·港湾验收'})
const scope = '/projects/' + project.id
const file = join(qaRoot, 'director-source.mp4')
execFileSync('ffmpeg', ['-v','error','-f','lavfi','-i','testsrc2=size=320x240:rate=24','-t','2',
  '-c:v','libx264','-pix_fmt','yuv420p','-threads','1',file], {timeout:20000})
const form = new FormData()
form.set('file',new Blob([await readFile(file)]),'原创验收视频.mp4')
form.set('authorization','FFmpeg 自制素材，仅作本机验收')
const asset = await api(scope+'/assets',{method:'POST',body:form})
const entity = (kind,title,content) => post(scope+'/story/entities',{kind,title,content,idempotency_key:kind})
const script = await entity('script','港湾故事',{body:'港湾灯塔点亮。'})
const episode = await entity('episode','港湾首集',{number:1,body:'打开灯塔的灯。',source_version_id:script.version_id})
const shots = await entity('storyboard','港湾首集分镜',{source_version_id:episode.version_id,
  shots:[{number:1,description:'港湾亮起',planned_duration:1}]})
const bible = await entity('story_bible','港湾制作计划',{script_version_id:script.version_id,theme:'港湾',world:'虚构港湾',
  episodes:[{episode_version_id:episode.version_id,storyboard_version_id:shots.version_id,target_duration_ms:1000}]})
const fixed = await post(`/series/entities/${bible.id}/approve`,{expected_version:1,note:'确认验收计划',idempotency_key:'manual-review'})
const edit = await entity('timeline','港湾首集剪辑',{source_version_id:fixed.version_id,profile:'square',frames:24,
  tracks:[{id:'video',role:'main',clips:[{id:'clip',asset_id:asset.id,at:0,frames:24}]}]})
const batch = await post('/production'+scope+'/runs',{plan_version_id:fixed.version_id,idempotency_key:'batch',
  timelines:[{number:1,timeline_version_id:edit.version_id}]})
await wait(async () => {
  const item = await api('/production/runs/'+batch.id)
  if (item.status === 'needs_rework' || item.status === 'needs_review') throw new Error(JSON.stringify(item))
  return item.status === 'passed'
}, 'verified production batch',40000)

const { command, evaluate, contains, click, setField, screenshot, errors, close } = await openChrome(19248)
const root = '/director'+scope+'/plans'
const state = () => evaluate("document.querySelector('[data-testid=director-plan-status]')?.textContent.trim()")
const selected = () => evaluate("document.querySelector('.director-history select')?.value")
try {
  await wait(()=>contains('服务就绪'),'workbench connected')
  await setField('当前项目',project.id)
  await click('AI 总导演')
  await wait(()=>contains('制作指令'),'director opened')
  await setField('制作指令','按固定时间轴在本机合成')
  await setField('工作流','render')
  await wait(()=>evaluate(`Array.from(document.querySelectorAll('select option')).some(item=>item.value===${JSON.stringify(edit.id)})`),'timeline available')
  await setField('时间轴',edit.id)
  await wait(()=>evaluate(`Array.from(document.querySelectorAll('select option')).some(item=>item.value===${JSON.stringify(edit.version_id)})`),'fixed version available')
  await click('生成执行计划')
  await wait(async()=>await state()==='待批准','draft persisted')
  const renderPlan = await selected()
  assert.equal((await api(root+'/'+renderPlan)).task,null)
  await command('Page.reload')
  await wait(async()=>await state()==='待批准','draft persists across reload')
  await click('批准并执行')
  await wait(async()=>await state()==='处理成功','Worker render completed',40000)
  await wait(()=>evaluate("document.querySelector('video[aria-label=总导演成片预览]')?.readyState >= 1"),'render preview decodes')
  const rendered = await api(root+'/'+renderPlan)
  assert.equal(rendered.external_cost_cents,0)
  assert.equal((await fetch(`${base}/api/tasks/${rendered.task.id}/output`,{headers:{range:'bytes=0-31'}})).status,206)
  await screenshot('director-render.png')

  await setField('工作流','release')
  await setField('制作指令','制作合规交付包')
  await setField('已通过质检的批次',batch.id)
  await setField('交付包标题','港湾验收交付')
  await setField('目标平台标识','local-test')
  await click('生成执行计划')
  await wait(()=>contains('交付授权尚未通过'),'unapproved rights blocked')
  assert.equal((await api(root)).length,1)
  await post(`/library/assets/${asset.id}/rights`,{status:'approved',source_type:'owned',holder:'原创验收项目',
    evidence:'本机 FFmpeg 自制',commercial:true,regions:['CN'],platforms:['local-test'],idempotency_key:'rights'})
  await click('生成执行计划')
  await wait(async()=>await state()==='待批准','authorized package awaits approval')
  const packagePlan = await selected()
  await click('批准并执行')
  await wait(async()=>await state()==='处理成功','Worker packaging completed',40000)
  const pack = await api(root+'/'+packagePlan)
  const zip = await fetch(base + `/api/delivery/packages/${pack.task.id}/file`)
  assert.equal(zip.status,200)
  assert.equal(Buffer.from(await zip.arrayBuffer()).subarray(0,2).toString(),'PK')
  assert.deepEqual(errors,[])
  await screenshot('director-delivery.png')
  await writeFile(join(evidenceDir,'director-browser.json'), JSON.stringify({
    project:project.id, fixed_timeline:edit.version_id, render:rendered, delivery:pack,
    reload_preserved_draft:true, unauthorized_delivery_blocked:true, real_api_budget_micros:0,
  },null,2)+'\n')
  console.log('PRISM director approved a local render and rights-gated delivery')
} finally {
  await close()
}
