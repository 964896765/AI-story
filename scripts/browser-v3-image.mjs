import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { readFile, writeFile } from 'node:fs/promises'
import { join } from 'node:path'
import { api, base, evidenceDir, openChrome, post, qaRoot, wait } from './chrome-qa.mjs'

await wait(async()=>{
  try { return (await api('/health')).ready && (await api('/queue')).workers.some(worker=>worker.online) }
  catch { return false }
},'isolated image services')
const project=await post('/projects',{name:'图片候选验收 · 港灯'})
const root='/projects/'+project.id
const endpoint='/generation'+root+'/images'
const live=await api(endpoint+'/capabilities')
assert.equal(live.live_available,false)
assert.equal(live.quote,null)
const spec=await post(root+'/production-specs',{expected_version:0,idempotency_key:'spec',settings:{
  episode_count:1,episode_duration_ms:1500,style:'夜景线稿',profile:'square',width:720,height:720,fps:24,
  platform:'local-test',region:'CN',budget_cents:0,
}})
const file=join(qaRoot,'test-reference.png')
execFileSync('ffmpeg',['-v','error','-f','lavfi','-i','testsrc2=size=256x256','-frames:v','1','-threads','1',file],{timeout:15000})
const payload=new FormData()
payload.set('file',new Blob([await readFile(file)]),'test-reference.png')
payload.set('authorization','本机 FFmpeg 自制测试参考图')
const reference=await api(root+'/assets',{method:'POST',body:payload})
const source=await post(root+'/story/entities',{kind:'character',title:'港灯守灯人',idempotency_key:'anchor',content:{
  appearance:'深蓝外套，固定佩戴铜色胸针',reference_asset_ids:[reference.id],production_spec_version_id:spec.id,
}})
const {command,evaluate,click,setField,screenshot,errors,close}=await openChrome(19247)
try {
  const panel=(text)=>evaluate(`document.querySelector('#image-candidates')?.innerText.includes(${JSON.stringify(text)})`)
  const hasOption=(value)=>evaluate(`document.querySelector('#image-candidates option[value=${JSON.stringify(value)}]')!==null`)
  await command('Page.navigate',{url:base+'/ai/candidates?project='+project.id+'#image-candidates'})
  await wait(()=>hasOption(source.version_id),'saved fixed character available')
  await wait(()=>hasOption(spec.id),'saved fixed spec available')
  await setField('固定制作规格',spec.id)
  await setField('图片固定来源',source.version_id)
  await setField('图片提示词','验收候选工作流，守灯人的画面规格')
  await click('提交图片候选')
  await wait(()=>panel('技术检查通过'),'backend decoded image and returned status')
  const [result]=await api(endpoint)
  assert.equal(result.production_spec.id,spec.id)
  assert.equal(result.source.id,source.version_id)
  assert.equal(result.actual_cost_micros,0)
  assert.equal(result.mode,'mock')
  await wait(()=>evaluate("document.querySelector('img[alt=图片候选]')?.naturalWidth===1024 && document.querySelector('img[alt=固定参考图]')?.naturalWidth===256"),'both original browser images loaded')
  const output=await fetch(base+'/api'+endpoint+'/'+result.id+'/file')
  assert.equal(createHash('sha256').update(Buffer.from(await output.arrayBuffer())).digest('hex'),result.output.sha256)
  assert.equal((await api(root+'/assets')).length,1)
  await setField('图片审核意见','核对离线模拟预览、版本和审核记录。')
  assert(await evaluate("Array.from(document.querySelectorAll('#image-candidates button')).find(button=>button.innerText==='保存图片审核').disabled"))
  for (let index=0;index<result.checks.length;index++) {
    await evaluate(`document.querySelectorAll('#image-candidates fieldset input[type=checkbox]')[${index}].click()`)
  }
  await click('保存图片审核')
  await wait(()=>panel('图片审核通过'),'review bound to output and reference')
  await setField('图片入库标题','港灯 · 离线模拟图')
  await click('采纳为图片素材')
  await wait(()=>panel('已入库'),'adopt explicitly')
  const [adopted]=await api(endpoint)
  const asset=(await api(root+'/assets')).find(item=>item.id===adopted.output.adoption.asset_id)
  assert(asset.media_info.simulated && asset.sha256===result.output.sha256)
  assert.equal(adopted.output.review.reference.sha256,reference.sha256)
  await command('Page.reload')
  await wait(()=>panel('已入库'),'persistent review and adoption after reload')
  await command('Page.navigate',{url:base+'/production?project='+project.id})
  await wait(()=>evaluate(`Array.from(document.querySelectorAll('a')).some(link=>link.innerText==='打开图片审核' && link.href.includes(${JSON.stringify(adopted.id)}))`),'queue links to the exact candidate')
  await evaluate(`Array.from(document.querySelectorAll('a')).find(link=>link.innerText==='打开图片审核' && link.href.includes(${JSON.stringify(adopted.id)})).click()`)
  await wait(()=>panel('已入库'),'reopen exact approved image from production queue')
  await wait(()=>evaluate("document.querySelector('img[alt=图片候选]')?.naturalWidth===1024"),'image loaded after reload')
  await evaluate("document.querySelector('#image-candidates').scrollIntoView({block:'start'})")
  await screenshot('image-candidate-workspace.png')
  await command('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true})
  assert(await evaluate('document.documentElement.scrollWidth<=window.innerWidth+1'))
  assert.deepEqual(errors,[])
  await writeFile(join(evidenceDir,'image-candidate-browser.json'),JSON.stringify({
    mode:result.mode,width:result.output.width,height:result.output.height,
    candidate_sha256:result.output.sha256,reference_sha256:reference.sha256,adoption_survives_reload:true,queue_link_opens_candidate:true,
    required_checklist_blocked_until_checked:true,real_execution_enabled:false,external_cost_micros:result.actual_cost_micros,
    mobile_no_horizontal_overflow:true,javascript_errors:errors,
  },null,2)+'\n')
  console.log('Image Chrome: decoded candidate, reference, review, asset adoption and browser reload passed.')
} catch (error) {
  console.error(await evaluate("document.querySelector('#image-candidates')?.innerText || document.body.innerText.slice(-3000)"))
  throw error
} finally { await close() }
