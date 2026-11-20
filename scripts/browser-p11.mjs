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
const blackClip=join(qaRoot,'owned-black.mp4')
execFileSync('ffmpeg',['-v','error','-f','lavfi','-i','testsrc2=size=320x240:rate=24:duration=1',
  '-f','lavfi','-i','sine=frequency=530:sample_rate=48000:duration=1','-t','1','-c:v','libx264',
  '-c:a','aac','-threads','1',clip],{timeout:20000})
execFileSync('ffmpeg',['-v','error','-f','lavfi','-i','color=black:size=320x240:rate=24:duration=1',
  '-c:v','libx264','-threads','1',blackClip],{timeout:20000})
async function upload(file,name){
  const data=new FormData()
  data.set('file',new Blob([await readFile(file)]),name)
  data.set('authorization','自行生成的本机验收样本')
  return api(path+'/assets',{method:'POST',body:data})
}
const asset=await upload(clip,'海港短样本.mp4')
const black=await upload(blackClip,'待替换黑场.mp4')
const create=(kind,title,content,idempotency_key)=>post(path+'/story/entities',{kind,title,content,idempotency_key})
const script=await create('script','海港短片',{body:'港口亮起一盏灯。'},'source')
const episode=await create('episode','海港',{body:'港口亮灯',number:1,source_version_id:script.version_id},'episode')
const board=await create('storyboard','定镜分镜',{source_version_id:episode.version_id,
  shots:[{number:1,shot_id:'harbor-shot',description:'港口',planned_duration:1}]},'board')
const bible=await create('story_bible','海港试制',{script_version_id:script.version_id,theme:'照明',world:'虚构港口',
  episodes:[{episode_version_id:episode.version_id,storyboard_version_id:board.version_id,target_duration_ms:1000}]},'bible')
const approved=await post('/series/entities/'+bible.id+'/approve',{expected_version:1,note:'自编试制审核通过',idempotency_key:'approved'})
const visual={id:'main',role:'main',clips:[{id:'repair-me',asset_id:black.id,at:0,frames:15},
  {id:'keep-me',asset_id:asset.id,at:15,frames:9}]}
const draft={source_version_id:approved.version_id,profile:'square',frames:24,tracks:[visual]}
const bad=await create('timeline','无音轨待修',draft,'no-audio')
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
  await wait(()=>contains('检测到连续黑场'),'real timed black frames finding')
  const [initial]=await api('/production'+path+'/runs')
  assert.equal(initial.status,'needs_rework')
  const initialDetail=await api('/production/runs/'+initial.id)
  const finding=initialDetail.episodes[0].qc.issues.find(issue=>issue.code==='black_frames')
  assert.deepEqual(finding.clips,['repair-me'])
  await click('项目总览')
  await click('查看待处理分集')
  await wait(()=>evaluate("document.activeElement?.id==='production-episode-1'"),'overview deep link focuses affected episode')
  await evaluate("Array.from(document.querySelectorAll('.production li')).find(item=>item.textContent.includes('检测到连续黑场')).querySelector('.finding-preview').click()")
  await wait(()=>evaluate(`(() => {const video=document.querySelector('.production video');
    return video?.readyState>=1 && Math.abs(video.currentTime-${finding.start_ms/1000})<.08})()`),'real playback seeks to black-frame start')
  await screenshot('p11-qc.png')
  await click('定位关联片段')
  await wait(()=>evaluate("document.activeElement?.dataset.clipId==='repair-me'"),'focused exactly the implicated clip')
  await screenshot('p11-focused-clip.png')
  await setField('片段素材',asset.id)
  await setField('附加轨道','dialogue')
  await click('添加轨道')
  await evaluate("document.querySelectorAll('.lane')[1].querySelectorAll('.lane-controls button')[2].click()")
  await wait(()=>evaluate("document.querySelector('.timeline-session fieldset legend')?.textContent==='对白片段'"),'dialogue clip added')
  await setField('片段素材',asset.id)
  await click('保存时间轴版本')
  await wait(()=>contains('时间轴 v2 已保存'),'fixed version appended')
  const [good]=(await api(path+'/story/entities?kind=timeline')).items
  await click('返回原质检批次')
  await wait(()=>contains('检测到连续黑场'),'returned to the original batch')
  await wait(()=>evaluate("document.activeElement?.id==='production-episode-1'"),'timeline return restores episode focus')
  assert.equal(await evaluate("document.querySelector('.production .version-list button[aria-pressed=true]')!==null"),true)
  await click('按此批次局部返工')
  await choose(good.version_id)
  await click('提交渲染和质检')
  await wait(()=>evaluate("document.querySelector('.run-summary')?.textContent.includes('批次 通过') && document.querySelector('.run-summary')?.textContent.includes('1/1 集通过')"),'real rerender and QC passed')
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
    fixed_run:result.id,detection:['missing_audio','black_frames'],actual_rerender:true,verified_preview:true,
    linked_clip:finding.clips[0],black_range_ms:[finding.start_ms,finding.end_ms],returned_to_batch:true,
    overview_deep_link_focused:true, finding_preview_seek:true,
    fixed_timeline_version:good.version_id,
    checks_after_fix:checked.episodes[0].qc.issues.length,javascript_errors:errors,
  },null,2)+'\n')
  console.log('P11 browser: real timed black frames, focused clip, corrected version, return and verified re-render passed.')
} catch(error){
  console.error(await evaluate('document.body.innerText.slice(-7000)'))
  throw error
} finally{await close()}
