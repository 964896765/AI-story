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
const entity = (kind,title,content) => post(scope+'/story/entities',{kind,title,content,idempotency_key:kind+':'+title})
const script = await entity('script','港湾故事',{body:'港湾灯塔点亮。'})
const episodes = []
for (const number of [1,2]) {
  const episode = await entity('episode','港湾第'+number+'集',{number,body:'打开灯塔的灯。',source_version_id:script.version_id})
  const shots = await entity('storyboard','港湾分镜 '+number,{source_version_id:episode.version_id,
    shots:[{number:1,description:'港湾亮起',planned_duration:1}]})
  episodes.push({episode_version_id:episode.version_id,storyboard_version_id:shots.version_id,target_duration_ms:1000})
}
const bible = await entity('story_bible','港湾制作计划',{script_version_id:script.version_id,theme:'港湾',world:'虚构港湾',
  episodes})
const fixed = await post(`/series/entities/${bible.id}/approve`,{expected_version:1,note:'确认验收计划',idempotency_key:'manual-review'})
const makeEdit = (title,sourceIn=0) => entity('timeline',title,{source_version_id:fixed.version_id,profile:'square',frames:24,
  tracks:[{id:'video',role:'main',clips:[{id:'clip',asset_id:asset.id,at:0,source_in:sourceIn,frames:24}]}]})
const edit = await makeEdit('港湾首集剪辑')
const second = await makeEdit('港湾第二集剪辑')
const newSecond = await makeEdit('港湾第二集返工剪辑',6)
const runsRoot = '/production'+scope+'/runs'

const { command, evaluate, contains, click, setField, screenshot, errors, close } = await openChrome(19248)
const root = '/director'+scope+'/plans'
const state = () => evaluate("document.querySelector('[data-testid=director-plan-status]')?.textContent.trim()")
const selected = () => evaluate("document.querySelector('.director-history select')?.value")
const hasOption = id => evaluate(`Array.from(document.querySelectorAll('select option')).some(item=>item.value===${JSON.stringify(id)})`)
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

  await setField('工作流','batch')
  await setField('制作指令','生产港湾两集并执行技术质检')
  await wait(()=>hasOption(fixed.version_id),'approved production plan selectable')
  await setField('已批准制作计划',fixed.version_id)
  await wait(()=>hasOption(second.version_id),'series timeline options')
  await setField('第 1 集时间轴',edit.version_id)
  await setField('第 2 集时间轴',second.version_id)
  await click('生成执行计划')
  await wait(async()=>await state()==='待批准','two-episode plan awaits approval')
  const batchPlan = await selected()
  assert.equal((await api(runsRoot)).length,0)
  await screenshot('director-batch-draft.png')
  await click('批准并执行')
  await wait(async()=>await state()==='质检通过','two-episode render and QC completed',40000)
  const initial = await api(root+'/'+batchPlan)
  assert.equal(initial.run.passed,2)
  assert(initial.run.episodes.every(item=>item.render_status==='succeeded' && item.qc_status==='succeeded'))
  await command('Page.reload')
  await wait(async()=>await state()==='质检通过','approved batch reloads and retrieves actual result')
  await setField('工作流','batch')
  await setField('制作指令','只更换第二集时间轴')
  await wait(()=>hasOption(initial.run_id),'provides batch for partial rework')
  await setField('基于既有批次',initial.run_id)
  await wait(()=>hasOption(newSecond.version_id),'rework options use the original plan')
  await setField('第 2 集时间轴',newSecond.version_id)
  await click('生成执行计划')
  await wait(async()=>await state()==='待批准','rework plan awaits approval')
  const reworkPlan = await selected()
  const preview = await api(root+'/'+reworkPlan)
  assert.deepEqual(preview.preview.map(item=>item.mode),['reuse','render'])
  await click('批准并执行')
  await wait(async()=>await state()==='质检通过','partial rework completed',40000)
  const rework = await api(root+'/'+reworkPlan)
  const batch = rework.run
  assert.equal(batch.reused,1)
  assert.equal(batch.episodes[0].render_task_id,initial.run.episodes[0].render_task_id)
  assert.notEqual(batch.episodes[1].render_task_id,initial.run.episodes[1].render_task_id)
  await screenshot('director-batch-rework.png')
  const productionLink = await evaluate("Array.from(document.querySelectorAll('a')).find(item=>item.textContent.trim()==='查看生产批次')?.href")
  assert.equal(new URL(productionLink).searchParams.get('run'), batch.id)

  await setField('工作流','release')
  await setField('制作指令','制作合规交付包')
  await wait(()=>hasOption(batch.id),'completed rework can be selected for delivery')
  await setField('已通过质检的批次',batch.id)
  await setField('交付包标题','港湾验收交付')
  await setField('目标平台标识','local-test')
  await click('生成执行计划')
  await wait(()=>contains('交付授权尚未通过'),'unapproved rights blocked')
  assert.equal((await api(root)).length,3)
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
    project:project.id, fixed_timeline:edit.version_id, render:rendered, batch:initial, rework, delivery:pack,
    reload_preserved_draft:true, unauthorized_delivery_blocked:true, real_api_budget_micros:0,
  },null,2)+'\n')
  console.log('PRISM director approved a local render, a two-episode batch, scoped rework, and rights-gated delivery')
} finally {
  await close()
}
