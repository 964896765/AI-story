import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { readFile, writeFile } from 'node:fs/promises'
import { join } from 'node:path'
import { api, base, evidenceDir, openChrome, post, qaRoot, wait } from './chrome-qa.mjs'

await wait(async()=>{
  try {return (await api('/health')).ready&&(await api('/queue')).workers.some(worker=>worker.online)} catch{return false}
},'isolated app')
const project=await post('/projects',{name:'P8 静图运镜样本'})
const path='/projects/'+project.id
const picture=join(qaRoot,'generated-bars.png')
execFileSync('ffmpeg',['-v','error','-f','lavfi','-i','testsrc2=size=320x240:rate=24','-frames:v','1',
  '-threads','1','-update','1',picture],{timeout:20000})
const upload=new FormData()
upload.set('file',new Blob([await readFile(picture)],{type:'image/png'}),'自有图案.png')
upload.set('authorization','自行生成的彩色测试图，用于本机验收')
const asset=await api(path+'/assets',{method:'POST',body:upload})
const {command,evaluate,contains,click,setField,screenshot,errors,close}=await openChrome(19228)
try{
  await wait(()=>contains('服务就绪'),'app ready')
  await setField('当前项目',project.id)
  await click('生成候选')
  await wait(()=>evaluate(`document.querySelector('option[value="${asset.id}"]')!==null`),'owned picture visible')
  await setField('参考图片',asset.id)
  await setField('成片帧数','12')
  await setField('画幅','square')
  await click('提交运镜候选')
  await wait(()=>contains('已排队 2 个本地候选'),'two candidates queued')
  await click('预览推进')
  await wait(()=>evaluate("document.querySelector('video')?.readyState>=1"),'browser verified local motion media')
  await wait(()=>evaluate("document.querySelector('.compare-control option[value]:not([value=\"\"])')!==null"),'second local candidate is ready for comparison')
  const alternate=await evaluate("document.querySelector('.compare-control option[value]:not([value=\"\"])').value")
  await setField('A/B 对比候选',alternate)
  await wait(()=>evaluate("[...document.querySelectorAll('.candidate-monitors video')].length===2 && [...document.querySelectorAll('.candidate-monitors video')].every(video=>video.readyState>=1)"),'both actual local candidates decode side by side')
  await setField('素材标题','审阅通过的运镜')
  await setField('采纳说明','检视画面方向和画幅后批准用于本地测试剪辑。')
  await screenshot('p8-motion-candidates.png')
  await evaluate("Array.from(document.querySelectorAll('button')).find(b=>b.textContent.trim()==='采纳为视频素材').focus()")
  await command('Input.dispatchKeyEvent',{type:'keyDown',key:'Enter',code:'Enter',text:'\r',windowsVirtualKeyCode:13})
  await command('Input.dispatchKeyEvent',{type:'keyUp',key:'Enter',code:'Enter',windowsVirtualKeyCode:13})
  await wait(()=>contains('已采纳为项目素材'),'keyboard approval')
  const candidates=await api('/generation'+path+'/candidates')
  assert.equal(candidates.length,2)
  const selected=candidates.find(candidate=>candidate.selected_asset_id)
  assert.equal(selected.output.actual_external_cost_micros,0)
  assert.notEqual(candidates[0].output.sha256,candidates[1].output.sha256)
  const range=await fetch(base+'/api/generation/candidates/'+selected.id+'/video',{headers:{Range:'bytes=0-99'}})
  assert.equal(range.status,206)
  assert.equal((await range.arrayBuffer()).byteLength,100)
  await click('智能二创')
  await wait(()=>contains('审阅通过的运镜.mp4'),'selected candidate selectable by downstream editor')
  assert.deepEqual(errors,[])
  await writeFile(join(evidenceDir,'p8-browser-acceptance.json'),JSON.stringify({
    checked_at:new Date().toISOString(),browser:'Installed Chrome headless',actual_candidates:candidates.length,
    selected_asset_id:selected.selected_asset_id,selected_task_id:selected.id,sha256:selected.output.sha256,
    browser_metadata_decoded:true,real_ab_playback:true,range_status:range.status,downstream_asset_selectable:true,
    external_cost_micros:0,physical_resource:'local_cpu',keyboard_adoption:true,javascript_errors:errors,
  },null,2)+'\n')
  console.log('P8 local branch: actual video candidates, browser playback and downstream adoption passed.')
} catch(error){
  console.error(await evaluate('document.body.innerText.slice(-6000)'))
  throw error
} finally{await close()}
