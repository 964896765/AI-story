import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { readFile, writeFile } from 'node:fs/promises'
import { join } from 'node:path'
import { api, evidenceDir, openChrome, post, qaRoot, wait } from './chrome-qa.mjs'

await wait(async()=>{
  try{return (await api('/health')).ready&&(await api('/queue')).workers.some(node=>node.online)}catch{return false}
},'isolated app')
const project=await post('/projects',{name:'P11 整剧质检与返工样本'})
const path='/projects/'+project.id
const clip=join(qaRoot,'owned-audio-video.mp4')
execFileSync('ffmpeg',['-v','error','-f','lavfi','-i','testsrc2=size=320x240:rate=24:duration=1',
  '-f','lavfi','-i','sine=frequency=530:sample_rate=48000:duration=1','-t','1','-c:v','libx264',
  '-c:a','aac','-threads','1',clip],{timeout:20000})
const data=new FormData()
data.set('file',new Blob([await readFile(clip)]),'海港短样本.mp4')
data.set('authorization','自行生成的本机验收样本')
const asset=await api(path+'/assets',{method:'POST',body:data})
const create=(kind,title,content,idempotency_key)=>post(path+'/story/entities',{kind,title,content,idempotency_key})
const script=await create('script','海港短片',{body:'港口亮起一盏灯。'},'source')
const episode=await create('episode','海港',{body:'港口亮灯',number:1,source_version_id:script.version_id},'episode')
const board=await create('storyboard','定镜分镜',{source_version_id:episode.version_id,
  shots:[{number:1,shot_id:'harbor-shot',description:'港口',planned_duration:1}]},'board')
const bible=await create('story_bible','海港试制',{script_version_id:script.version_id,theme:'照明',world:'虚构港口',
  episodes:[{episode_version_id:episode.version_id,storyboard_version_id:board.version_id,target_duration_ms:1000}]},'bible')
const approved=await post('/series/entities/'+bible.id+'/approve',{expected_version:1,note:'自编试制审核通过',idempotency_key:'approved'})
const visual={id:'main',role:'main',clips:[{id:'v',asset_id:asset.id,at:0,frames:24}]}
const voice={id:'voice',role:'dialogue',clips:[{id:'a',asset_id:asset.id,at:0,frames:24}]}
const draft={source_version_id:approved.version_id,profile:'square',frames:24,tracks:[visual]}
const bad=await create('timeline','无音轨待修',draft,'no-audio')
const good=await create('timeline','音轨已修复',{...draft,tracks:[visual,voice]},'corrected')
const {evaluate,contains,click,setField,screenshot,errors,close}=await openChrome(19231)
async function choose(id){
  await wait(()=>evaluate(`document.querySelector('.production option[value="${id}"]')!==null`),'fixed timeline displayed')
  await evaluate(`(() => {
    const input=document.querySelector('.production .editor-grid select')
    input.value=${JSON.stringify(id)}
    input.dispatchEvent(new Event('change',{bubbles:true}))
  })()`)
}
try{
  await wait(()=>contains('服务就绪'),'app ready')
  await setField('当前项目',project.id)
  await click('批量生产')
  await wait(()=>evaluate("document.querySelector('.production summary')!==null"),'production workbench loaded')
  await evaluate("document.querySelector('.production summary').click()")
  await wait(()=>evaluate(`document.querySelector('.production option[value="${approved.version_id}"]')!==null`),'approved plan loaded')
  await setField('已批准制作计划',approved.version_id)
  await choose(bad.version_id)
  await evaluate("document.querySelector('.production input[type=checkbox]').click()")
  await click('提交渲染和质检')
  await wait(()=>contains('本批次要求音轨，当前输出没有音轨'),'real missing audio finding')
  const [initial]=await api('/production'+path+'/runs')
  assert.equal(initial.status,'needs_rework')
  await screenshot('p11-qc.png')
  await click('按此批次局部返工')
  await choose(good.version_id)
  await click('提交渲染和质检')
  await wait(()=>contains('批次 通过 · 1/1 集通过'),'real rerender and QC passed')
  const [result]=await api('/production'+path+'/runs')
  assert.equal(result.status,'passed')
  const checked=await api('/production/runs/'+result.id)
  assert.equal(checked.previous_run_id,initial.id)
  assert.equal(checked.episodes[0].timeline_version_id,good.version_id)
  await click('预览本集')
  await wait(()=>evaluate("document.querySelector('.production video')?.readyState>=1"),'verified movie preview')
  assert.deepEqual(errors,[])
  await writeFile(join(evidenceDir,'p11-browser-acceptance.json'),JSON.stringify({
    checked_at:new Date().toISOString(),browser:'Installed Chrome headless',initial_run:initial.id,
    fixed_run:result.id,detection:'missing_audio',actual_rerender:true,verified_preview:true,
    checks_after_fix:checked.episodes[0].qc.issues.length,javascript_errors:errors,
  },null,2)+'\n')
  console.log('P11 browser: real technical finding, localized correction, verified re-render and preview passed.')
} catch(error){
  console.error(await evaluate('document.body.innerText.slice(-7000)'))
  throw error
} finally{await close()}
