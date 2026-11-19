import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { readFile, writeFile } from 'node:fs/promises'
import { join } from 'node:path'
import { api, base, evidenceDir, openChrome, post, qaRoot, wait } from './chrome-qa.mjs'

await wait(async()=>{
  try{return (await api('/health')).ready&&(await api('/queue')).workers.some(node=>node.online)}catch{return false}
},'isolated app')
const project=await post('/projects',{name:'P13 本地运营业务样本'})
const path='/projects/'+project.id
const fixture=join(qaRoot,'owned-promo.mp4')
execFileSync('ffmpeg',['-v','error','-f','lavfi','-i','testsrc2=size=320x240:rate=24:duration=1',
  '-c:v','libx264','-threads','1',fixture],{timeout:20000})
const upload=new FormData()
upload.set('file',new Blob([await readFile(fixture)]),'本机宣传样本.mp4')
upload.set('authorization','自行生成，仅用于本机功能验证')
const asset=await api(path+'/assets',{method:'POST',body:upload})
const make=(kind,title,content,idempotency_key)=>post(path+'/story/entities',{kind,title,content,idempotency_key})
const script=await make('script','运营样本',{body:'自有试制镜头。'},'s')
const ep=await make('episode','第 1 集',{number:1,body:'测试镜头',source_version_id:script.version_id},'e')
const board=await make('storyboard','测试分镜',{source_version_id:ep.version_id,
  shots:[{number:1,description:'港口灯光',planned_duration:1}]},'b')
const bible=await make('story_bible','推广试制',{script_version_id:script.version_id,theme:'光',world:'海港',
  episodes:[{episode_version_id:ep.version_id,storyboard_version_id:board.version_id,target_duration_ms:1000}]},'p')
const approved=await post('/series/entities/'+bible.id+'/approve',{expected_version:1,note:'本机样本审核通过',idempotency_key:'approval'})
const timeline=await make('timeline','本机试制',{source_version_id:approved.version_id,frames:24,profile:'square',
  tracks:[{id:'main',role:'main',clips:[{id:'shot',asset_id:asset.id,at:0,frames:24}]}]},'t')
const run=await post('/production'+path+'/runs',{plan_version_id:approved.version_id,idempotency_key:'qc',
  timelines:[{number:1,timeline_version_id:timeline.version_id}]})
await wait(async()=>(await api('/production/runs/'+run.id)).status==='passed','real output passed')
await post('/library/assets/'+asset.id+'/rights',{status:'approved',source_type:'owned',
  holder:'自有试制人',evidence:'本机自制测试样本权利记录',commercial:true,regions:['CN'],
  platforms:['local-test'],idempotency_key:'fixture-right'})
const delivery=await post('/delivery'+path+'/packages',{run_id:run.id,title:'运营样本交付包',platform:'local-test',
  region:'CN',idempotency_key:'delivery'})
await wait(async()=>(await api('/delivery'+path+'/packages'))[0].status==='succeeded','delivered archive')
const { evaluate, contains, click, setField, screenshot, errors, close }=await openChrome(19233)
try{
  await wait(()=>contains('服务就绪'),'workbench ready')
  await setField('当前项目',project.id)
  await click('运营中心')
  await wait(()=>evaluate(`document.querySelector('option[value="${delivery.id}"]')!==null`),'authorized delivery visible')
  await evaluate("document.querySelector('.operations summary').click()")
  await setField('剧场或渠道名称','本机验收剧场')
  await setField('运营主体','本机合成样本主体')
  await setField('账号显示名','qa-account')
  await setField('平台标识','local-test')
  await setField('投放地域','CN')
  await setField('规则出处（HTTPS）','https://example.invalid/local-test')
  await setField('人工核验依据','隔离测试中登记的名义规则，不对应实际平台。')
  await evaluate("document.querySelector('.operations input[type=checkbox]').click()")
  await click('保存渠道')
  await wait(()=>contains('已保存渠道规则版本'),'channel saved')
  await setField('授权交付包',delivery.id)
  await setField('发行标题','试制发行的人工记录')
  await click('保存发行草稿')
  await wait(()=>contains('人工发行草稿已保存'),'manual draft')
  await setField('更新状态','planned')
  await setField('实际状态凭证','本地验收计划登记，未提交真实平台。')
  await click('登记人工结果')
  await wait(()=>contains('已登记人工发行状态'),'planning event recorded')
  const [publication]=await api('/distribution'+path+'/publications')
  assert.equal(publication.mode,'manual_record')
  assert.equal(publication.status,'planned')
  const [channel]=await api('/distribution'+path+'/channels')
  await setField('结算渠道',channel.id)
  const head='external_id,currency,kind,status,amount,period_start,period_end,evidence'
  await setField('结算 CSV',head+'\nqa-cash,CNY,cash,confirmed,30,2026-11-01,2026-11-01,合成验收凭证\nqa-ad,CNY,ad_credit,confirmed,100,2026-11-01,2026-11-01,合成广告金凭证')
  await click('导入结算记录')
  await wait(()=>contains('新增 2 条结算，跳过 0 条重复记录'),'initial settlement')
  await click('导入结算记录')
  await wait(()=>contains('新增 0 条结算，跳过 2 条重复记录'),'deduplicated settlement')
  assert(await contains('已记账现金差额 CNY 30.00'))
  assert(await contains('广告金 CNY 100.00'))
  await evaluate("Array.from(document.querySelectorAll('h2')).find(h=>h.textContent==='结算与经营记录').scrollIntoView({block:'start'})")
  await screenshot('p13-operations.png')
  await setField('推广来源交付包',delivery.id)
  await setField('推广标题','试制片段')
  await setField('推广片段秒数','0.5')
  await setField('简介','片段取自本机已通过质检且授权的成片。')
  await click('生成待审推广包')
  await wait(()=>contains('下载片段、封面和清单'),'real promo archive')
  const [promo]=await api('/distribution'+path+'/promotions')
  const payload=await fetch(base+'/api/distribution/promotions/'+promo.id+'/file')
  assert.equal(payload.status,200)
  assert.equal(Buffer.from(await payload.arrayBuffer()).subarray(0,2).toString(),'PK')
  assert.deepEqual(errors,[])
  await writeFile(join(evidenceDir,'p13-browser-acceptance.json'),JSON.stringify({
    checked_at:new Date().toISOString(),browser:'Installed Chrome headless',distribution_mode:publication.mode,
    recorded_status:publication.status,promo_zip_downloaded:true,settlements_inserted:2,duplicates_skipped:2,
    fixture_cash_micros:30000000,fixture_ad_credits_micros:100000000,actual_external_publishes:0,javascript_errors:errors,
  },null,2)+'\n')
  console.log('P13 browser: local theater records, verified promo ZIP and deduplicated settlement passed.')
} catch(error){
  console.error(await evaluate('document.body.innerText.slice(-7000)'))
  throw error
} finally {await close()}
