import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { readFile, writeFile } from 'node:fs/promises'
import { join } from 'node:path'
import { api, base, evidenceDir, openChrome, post, qaRoot, wait } from './chrome-qa.mjs'

await wait(async()=>{
  try{return (await api('/health')).ready&&(await api('/queue')).workers.some(node=>node.online)}catch{return false}
},'isolated app')
const project=await post('/projects',{name:'P12 授权交付链验收'})
const path='/projects/'+project.id
const fixture=join(qaRoot,'owned-harbor.mp4')
execFileSync('ffmpeg',['-v','error','-f','lavfi','-i','testsrc2=size=320x240:rate=24:duration=1',
  '-c:v','libx264','-threads','1',fixture],{timeout:20000})
const upload=new FormData()
upload.set('file',new Blob([await readFile(fixture)]),'港口自有样本.mp4')
upload.set('authorization','自行生成，仅用于本机功能验证')
const asset=await api(path+'/assets',{method:'POST',body:upload})
const make=(kind,title,content,idempotency_key)=>post(path+'/story/entities',{kind,title,content,idempotency_key})
const script=await make('script','港口样本',{body:'自有试制短镜头。'},'script')
const ep=await make('episode','第 1 集',{number:1,body:'海湾镜头',source_version_id:script.version_id},'ep')
const board=await make('storyboard','镜头',{source_version_id:ep.version_id,shots:[
  {number:1,description:'海湾镜头',planned_duration:1}]},'board')
const bible=await make('story_bible','海湾交付计划',{script_version_id:script.version_id,theme:'港口',
  world:'虚构海湾',episodes:[{episode_version_id:ep.version_id,storyboard_version_id:board.version_id,
  target_duration_ms:1000}]},'bible')
const approved=await post('/series/entities/'+bible.id+'/approve',{expected_version:1,note:'本机测试批准',
  idempotency_key:'approved'})
const edit=await make('timeline','海湾交付时间轴',{source_version_id:approved.version_id,frames:24,profile:'square',
  tracks:[{id:'main',role:'main',clips:[{id:'shot',asset_id:asset.id,at:0,frames:24}]}]},'edit')
const run=await post('/production'+path+'/runs',{plan_version_id:approved.version_id,idempotency_key:'qc',
  timelines:[{number:1,timeline_version_id:edit.version_id}]})
await wait(async()=>(await api('/production/runs/'+run.id)).status==='passed','production QC passed')

const { command,evaluate,contains,click,setField,screenshot,errors,close}=await openChrome(19232)
try{
  await wait(()=>contains('服务就绪'),'workbench ready')
  await setField('当前项目',project.id)
  await click('核对授权与交付')
  await wait(()=>evaluate(`document.querySelector('.library option[value="${run.id}"]')!==null`),'passed batch visible')
  await wait(()=>evaluate(`document.querySelector('.package-panel select')?.value==='${run.id}'`),'overview hands off fixed run')
  await command('Page.reload')
  await wait(()=>evaluate(`document.querySelector('.package-panel select')?.value==='${run.id}'`),'delivery reload preserves run')
  await setField('交付包名称','海湾交付 ZIP')
  await setField('目标平台标识','local-test')
  await setField('目标地域','CN')
  await click('检查交付条件')
  await wait(()=>contains('交付授权尚未通过'),'rights gate blocks missing record')
  assert.equal((await api('/delivery'+path+'/packages')).length,0)
  await screenshot('v3-04-preflight.png')

  await click('核对这项授权')
  await wait(()=>contains('权利方'),'rights form available')
  assert.equal(await evaluate("document.querySelector('.rights-panel select').value"),asset.id)
  await setField('核验状态','approved')
  await setField('权利方','自有样本制作者')
  await setField('授权或核验证据','确认这是本机为交付验证自行生成的测试素材。')
  await setField('平台标识（逗号分隔）','local-test')
  await setField('地域（两位大写代号）','CN')
  await evaluate("Array.from(document.querySelectorAll('label')).find(l=>l.textContent.trim()==='包含商用交付').querySelector('input').click()")
  await click('保存授权版本')
  await wait(()=>contains('已追加授权版本'),'rights persisted')
  await wait(()=>contains('质检与当前授权通过'),'readiness refresh after rights change')
  await click('核对授权并创建交付包')
  await wait(()=>contains('下载已验证 ZIP'),'real ZIP published')
  await evaluate("Array.from(document.querySelectorAll('a')).find(a=>a.textContent.trim()==='下载已验证 ZIP').scrollIntoView({block:'center'})")
  await screenshot('p12-delivery.png')
  const [delivery]=await api('/delivery'+path+'/packages')
  const file=await fetch(base+'/api/delivery/packages/'+delivery.id+'/file')
  assert.equal(file.status,200)
  const bytes=Buffer.from(await file.arrayBuffer())
  assert.equal(bytes.subarray(0,2).toString(),'PK')
  assert.equal(createHash('sha256').update(bytes).digest('hex'),delivery.sha256)
  await click('打开人工发行')
  await wait(()=>evaluate(`document.querySelector('.publication-panel select option[value="${delivery.id}"]')?.selected`),'same package preselected for manual registration')
  assert.equal((await api('/distribution'+path+'/publications')).length,0)
  await screenshot('v3-04-operations.png')
  await click('回到交付批次')
  await wait(()=>evaluate(`document.querySelector('.package-panel select')?.value==='${run.id}'`),'manual registration returns to the same run')
  assert.deepEqual(errors,[])
  await writeFile(join(evidenceDir,'p12-browser-acceptance.json'),JSON.stringify({
    checked_at:new Date().toISOString(),browser:'Installed Chrome headless',checked_run:run.id,package_task:delivery.id,
    missing_rights_blocked:true,recorded_rights_then_downloaded:true,zip_sha256_verified:true,zip_bytes:bytes.length,
    fixed_run_reloaded:true,read_only_preflight_verified:true,manual_package_handoff:true,
    javascript_errors:errors,
  },null,2)+'\n')
  console.log('P12 browser: missing rights blocked, rights confirmed, actual verified archive downloaded.')
} catch(error) {
  console.error(await evaluate('document.body.innerText.slice(-7000)'))
  throw error
} finally { await close() }
