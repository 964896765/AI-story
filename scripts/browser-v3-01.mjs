import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { readFile, writeFile } from 'node:fs/promises'
import { join } from 'node:path'
import { api, base, evidenceDir, openChrome, post, qaRoot, wait } from './chrome-qa.mjs'

await wait(async () => {
  try { return (await api('/health')).ready && (await api('/queue')).workers.some(worker => worker.online) }
  catch { return false }
}, 'local API and Worker')
const textStatus = await api('/text/status')
assert.equal(textStatus.live_authorized,false)
assert.equal(textStatus.default_live_budget_micros,0)
const project = await post('/projects', { name:'雾港来信', description:'原创验收短片。用自制参考图、固定剧本和本机 Worker 验证制作流程。' })
const empty = await post('/projects', { name:'空项目隔离验收' })
const path = '/projects/' + project.id
const image = join(qaRoot,'overview-cover.png'), movie = join(qaRoot,'overview-scene.mp4')
const gradient = 'gradients=s=640x360:r=24:c0=0x322942:c1=0xc78770:c2=0x36535e:n=3:x0=40:y0=50:x1=620:y1=220:speed=0.001'
const skyline = ['drawbox=x=0:y=258:w=640:h=102:color=0x243039:t=fill','drawbox=x=74:y=160:w=72:h=118:color=0x293442:t=fill',
  'drawbox=x=216:y=188:w=205:h=116:color=0x3b3345:t=fill','drawbox=x=350:y=132:w=40:h=104:color=0x372d3e:t=fill',
  'drawbox=x=512:y=205:w=93:h=82:color=0x313442:t=fill','drawbox=x=365:y=146:w=11:h=16:color=0xe2b77d:t=fill',
  'drawbox=x=0:y=311:w=640:h=49:color=0x1e262e:t=fill'].join(',')
execFileSync('ffmpeg',['-v','error','-filter_threads','1','-f','lavfi','-i',gradient,'-vf',skyline,'-frames:v','1','-threads','1',image],{timeout:20000})
execFileSync('ffmpeg',['-v','error','-filter_threads','1','-f','lavfi','-i',gradient,'-vf',skyline,'-t','2','-c:v','libx264','-pix_fmt','yuv420p','-threads','1',movie],{timeout:20000})
async function upload(file,name) {
  const data = new FormData()
  data.set('file',new Blob([await readFile(file)]),name)
  data.set('authorization','验收脚本使用 FFmpeg 自制，未包含第三方画面')
  return api(path+'/assets',{method:'POST',body:data})
}
const cover = await upload(image,'雾港参考图.png')
const media = await upload(movie,'码头夜景.mp4')
const script = await post(path+'/story/entities',{kind:'script',title:'雾港·首场',content:{body:'灯在雾里亮了一下。远处传来汽笛，信封被放进木盒。'},idempotency_key:'v3-script'})
const render = await post(path+'/tasks',{kind:'render',asset_id:media.id,story_version_id:script.version_id,parameters:{},idempotency_key:'v3-render'})
const provider = await post('/text/providers',{kind:'mock',label:'V3 离线验收',enabled:true,settings:{model:'offline-adaptation-fixture',mock_scenario:'success',input_per_million:'1',output_per_million:'2'}})
await post('/text'+path+'/budgets',{currency:'CNY',mode:'mock',limit_micros:1_000_000,idempotency_key:'v3-mock-budget'})
const call = await post('/text'+path+'/calls',{source_version_id:script.version_id,provider_id:provider.id,goal:'将开场整理为独立的待审草稿',idempotency_key:'v3-mock-call'})
await wait(async () => {
  const result = await api('/text/calls/'+call.id)
  const tasks = await api(path+'/tasks')
  const movieTask = tasks.find(task=>task.id===render.id)
  if (movieTask.status==='failed') throw new Error(movieTask.error)
  return result.status==='awaiting_review' && movieTask.status==='succeeded'
},'real render and clearly simulated draft',45000)
const stored = await api(path+'/overview')
assert.equal(stored.cover.id,cover.id)
assert.equal(stored.recent_renders[0].id,render.id)
assert.equal(stored.draft_review_count,1)
assert.equal(stored.draft_reviews[0].simulated,true)
assert.equal(stored.costs.every(row=>row.amount_micros==='0' && row.unknown===0),true)

const {command, evaluate, contains, click, setField, screenshot, errors, close} = await openChrome(19236)
const text = id => evaluate(`document.querySelector('[data-testid="${id}"]')?.textContent.trim()`)
const address = () => evaluate('location.pathname+location.search')
const size = (width,height,mobile=false) => command('Emulation.setDeviceMetricsOverride',{width,height,mobile,deviceScaleFactor:1})
try {
  await size(1440,900)
  await wait(()=>contains('服务就绪'),'workbench connected')
  assert.equal(await evaluate("document.querySelectorAll('nav a[data-workspace]').length"),12)
  await setField('当前项目',project.id)
  await wait(()=>text('overview-project').then(value=>value===project.name),'selected project bound to overview')
  await wait(()=>evaluate("document.querySelector('.feature-art img')?.naturalWidth>0"),'approved cover media decoded')
  assert.equal(await text('task-total'),'2')
  assert.equal(await text('review-total'),'1')
  assert.equal(await text('output-total'),'1')
  assert.equal(await text('overview-cost'),'¥0.00')
  await screenshot('v3-overview-1440.png')
  await evaluate("document.querySelector('.film-thumbnail').click()")
  await wait(()=>evaluate("document.querySelector('.output-modal-video')?.readyState>=1"),'actual output preview')
  assert.equal((await fetch(`${base}/api/tasks/${render.id}/output`,{headers:{Range:'bytes=0-99'}})).status,206)
  await command('Input.dispatchKeyEvent',{type:'keyDown',key:'Escape',code:'Escape',windowsVirtualKeyCode:27})
  await command('Input.dispatchKeyEvent',{type:'keyUp',key:'Escape',code:'Escape',windowsVirtualKeyCode:27})
  await wait(()=>evaluate("!document.querySelector('.output-modal-video')"),'preview escape')
  await evaluate("document.querySelector('#pending-review a').click()")
  await wait(()=>contains('待审核草稿 v1'),'overview review deep link opens the actual draft')
  assert.match(await address(),new RegExp(`call=${call.id}`))
  await command('Page.reload')
  await wait(()=>contains('待审核草稿 v1'),'review deep link reopened after reload')
  await click('项目总览')
  await wait(()=>text('overview-project').then(value=>value===project.name),'return to overview')
  const scopes = []
  for (const [width,height] of [[1920,1080],[1440,900],[1280,800],[390,844]]) {
    await size(width,height,width<500)
    await wait(()=>evaluate(`innerWidth===${width}`),'viewport updated')
    if (width < 500) await wait(()=>evaluate("getComputedStyle(document.querySelector('.app-sidebar')).visibility === 'hidden'"),'mobile drawer fully closed')
    assert.equal(await evaluate('document.documentElement.scrollWidth<=innerWidth'),true)
    scopes.push([width,height])
    if (width===390 || width===1920) await screenshot(`v3-overview-${width}.png`)
  }
  await evaluate("document.querySelector('button[aria-label=\"打开导航\"]').click()")
  await wait(()=>evaluate("document.querySelector('.app-sidebar').classList.contains('is-open')"),'mobile navigation open')
  await click('批量生产')
  await wait(()=>contains('持久化任务队列'),'mobile task queue visible')
  assert(!await evaluate("document.querySelector('.app-sidebar').classList.contains('is-open')"))
  await size(1440,900)
  const legacyPages = ['素材资产中心','智能解析','智能二创','剧情改编','漫剧定制','故事圣经','生成候选',
    '配音与字幕','多轨时间轴','批量生产','质检与导出','资源与交付','运营中心','运行诊断']
  for (const title of [...legacyPages,'角色与场景','分镜编辑','文本模型与预算']) {
    await click(title)
    await wait(()=>evaluate(`document.querySelector('main h1')?.textContent.trim()===${JSON.stringify(title)}`),'routed '+title)
  }
  await command('Page.navigate',{url:`${base}/project/analysis?project=${project.id}&asset=${media.id}`})
  await wait(()=>evaluate(`document.querySelector('.analysis-workspace select')?.value==='${media.id}'`),'direct analysis link preserves authorized asset')
  await click('项目总览')
  await wait(()=>text('overview-project').then(value=>value===project.name),'return to overview before project switch')
  await setField('当前项目',empty.id)
  await wait(()=>text('overview-project').then(value=>value===empty.name),'switch to empty project')
  assert.equal(await text('task-total'),'0')
  assert.equal(await text('review-total'),'0')
  assert.equal(await text('output-total'),'0')
  await click('新建项目')
  await wait(()=>evaluate("document.querySelector('main details[open] form')!==null"),'new project form opened from overview')
  await setField('项目名称','V3 浏览器新建项目')
  await setField('项目说明','独立测试库中的用户操作验收')
  await click('创建项目')
  await wait(()=>evaluate("document.querySelector('.project-picker select')?.selectedOptions[0]?.textContent === 'V3 浏览器新建项目'"),'created project persisted and selected')
  assert((await api('/projects')).some(item => item.name==='V3 浏览器新建项目'))
  await setField('当前项目',project.id)
  await wait(()=>evaluate("[...document.querySelectorAll('.asset')].some(item=>item.textContent.includes('码头夜景.mp4'))"),'owned video available in original asset page')
  await click('读取媒体信息')
  await wait(()=>evaluate("[...document.querySelectorAll('.asset')].find(item=>item.textContent.includes('码头夜景.mp4'))?.textContent.includes('已解析')"),'Worker probe refreshed in asset view',25000)
  assert.deepEqual(errors,[])
  const spec = await (await fetch(`http://127.0.0.1:${process.env.AI_STORY_QA_API_PORT}/openapi.json`)).json()
  const methods = new Set(['get','post','put','patch','delete','head','options'])
  const paths = Object.entries(spec.paths).flatMap(([route, operations])=>Object.keys(operations).filter(op=>methods.has(op)).map(method=>({path:route,method:method.toUpperCase()})))
  await writeFile(join(evidenceDir,'v3-01-browser-acceptance.json'),JSON.stringify({browser:'Installed Chrome headless',
    checked_at:new Date().toISOString(),viewports:scopes,primary_navigation_entries:12,legacy_pages_reached:legacyPages,
    additional_pages_reached:['角色与场景','分镜编辑','文本模型与预算'],actual_render_playback:true,deep_link_reload:true,project_isolation:true,
    actual_project_creation:true, asset_probe_auto_refresh:true,
    model_calls:{simulated:1,live:0,paid_micros:0},unknown_cost_count:0,openapi_operations:paths,javascript_errors:errors},null,2)+'\n')
  console.log('V3 overview: real project, FFmpeg output, recorded tasks, mock draft, deep links, and 12 navigation groups verified.')
} catch (error) {
  console.error(await evaluate('document.body.innerText.slice(-5000)'))
  throw error
} finally { await close() }
