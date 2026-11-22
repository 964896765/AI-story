import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { readFile, writeFile } from 'node:fs/promises'
import { join } from 'node:path'
import { api, base, evidenceDir, openChrome, post, qaRoot, wait } from './chrome-qa.mjs'

await wait(async()=>{
  try { return (await api('/health')).ready && (await api('/queue')).workers.some(worker=>worker.online) }
  catch { return false }
},'isolated Guardian services')
const project=await post('/projects',{name:'Guardian 原创测试剧 · 灯塔交信'})
const path='/projects/'+project.id
const create=(kind,title,content,idempotency_key)=>post(path+'/story/entities',{kind,title,content,idempotency_key})
const revise=(edition,content,idempotency_key)=>post('/story/entities/'+edition.id+'/versions',{
  title:edition.title,expected_version:edition.version,content,idempotency_key,
})
const approve=(edition,idempotency_key)=>post('/series/entities/'+edition.id+'/approve',{
  expected_version:edition.version,note:'核对原创试制分镜与锁定版本',idempotency_key,
})
const continuity=edition=>api('/series/versions/'+edition.version_id+'/continuity')
async function blocked(route,body,status){
  const response=await fetch(base+'/api'+route,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})
  assert.equal(response.status,status,await response.text())
}
async function artwork(name,{background='0x20445c',face='0xffc79a',coat='0x2ddd9a',subject=true}={}) {
  const filename=join(qaRoot,name+'.png')
  const shapes=[`drawbox=x=0:y=130:w=320:h=110:color=${background}:t=fill`,
    'drawbox=x=197:y=58:w=45:h=52:color=0xdfa582:t=fill','drawbox=x=179:y=110:w=80:h=100:color=0x5b4296:t=fill']
  if(subject)shapes.push(`drawbox=x=78:y=60:w=49:h=52:color=${face}:t=fill`,
    `drawbox=x=62:y=111:w=82:h=95:color=${coat}:t=fill`,'drawbox=x=44:y=138:w=26:h=18:color=white:t=fill')
  execFileSync('ffmpeg',['-v','error','-f','lavfi','-i','testsrc2=size=320x240','-vf',shapes.join(','),
    '-frames:v','1','-threads','1',filename],{timeout:15000})
  const upload=new FormData()
  upload.set('file',new Blob([await readFile(filename)]),name+'.png')
  upload.set('authorization','本次测试自行绘制，两名虚构角色')
  return api(path+'/assets',{method:'POST',body:upload})
}
const [coast,room,wrongIdentity,wrongWardrobe,wrongScene,wrongShot]=await Promise.all([
  artwork('coast'),artwork('room',{background:'0x543747'}),artwork('wrong-identity',{face:'0xba6847'}),
  artwork('wrong-wardrobe',{coat:'0xf54d58'}),artwork('wrong-scene',{background:'0xf7b942'}),artwork('wrong-shot',{subject:false}),
])
const installed=(await api('/voice/capabilities')).voices
const voice=installed.find(item=>item.locale==='zh-CN')
assert(voice,'Chinese Windows offline voice is required for this acceptance')
const novel=await create('novel','灯塔交信',{text:'阿青和守塔人在岸边见面，带着旧信进入灯室。',authorization:'原创验收剧'},'novel')
const script=await create('script','灯塔交信 · 剧本',{body:'日落前交信。阿青说「好。」',source_version_id:novel.version_id},'script')
const actor=await create('character','阿青',{identity:{traits:'浅色面部，左侧人物',wardrobes:{green:'绿色外衣'},local_voice:voice.name},reference_asset_ids:[coast.id]},'actor')
const keeper=await create('character','守塔人',{identity:{traits:'右侧人物',wardrobes:{violet:'紫色斗篷'}},reference_asset_ids:[room.id]},'keeper')
const exterior=await create('scene','灯塔外',{location:'海边',reference_asset_ids:[coast.id]},'coast')
const interior=await create('scene','灯室',{location:'灯塔室内',reference_asset_ids:[room.id]},'room')
const ids=[actor.version_id,keeper.version_id]
const canon={facts:{deadline:'日落前交信'},props:{letter:'白色旧信'},character_version_ids:ids,
  scene_version_ids:[exterior.version_id,interior.version_id],style:{description:'平面色块原画',reference_asset_ids:[coast.id]}}
const defects=[['identity',wrongIdentity],['wardrobe',wrongWardrobe],['scene',wrongScene],['shot_mismatch',wrongShot]]
const plans=[], boards=[]
for (const [offset,[scene,art]] of [[exterior,coast],[interior,room]].entries()) {
  const number=offset+1
  const episode=await create('episode',`第 ${number} 集`,{number,body:'两人在灯塔接力交信',source_version_id:script.version_id},'ep-'+number)
  const states=[{character_version_id:ids[0],wardrobe_id:'green',left_hand:'letter',action:'站定',position:'画面左侧'},
    {character_version_id:ids[1],wardrobe_id:'violet',action:'站定',position:'画面右侧'}]
  const shots=Array.from({length:5},(_,index)=>({number:index+1,shot_id:`ep${number}-shot${index+1}`,description:`灯塔镜头 ${index+1}`,
    planned_duration:number===1 && index===4 ? 2 : 1,scene_version_id:scene.version_id,character_version_ids:ids,strategy:'still_motion',
    contract:{visual:'左侧阿青持白信，右侧是守塔人',facts:{deadline:'日落前交信'},opening:structuredClone(states),closing:structuredClone(states),
      source_image_asset_ids:[art.id,...(number===1 && index===0 ? defects.map(([,image])=>image.id):[])]},
  }))
  if(number===1)Object.assign(shots[4],{dialogue:'好。',dialogue_ms:600,speaker_version_id:actor.version_id})
  const invalid=structuredClone(shots)
  if(number===1){
    invalid[1].contract.opening[0].left_hand=null
    invalid[1].contract.opening[0].right_hand='letter'
    invalid[1].contract.opening[0].action='奔跑'
    invalid[2].contract.facts.deadline='午夜交信'
  }
  const board=await create('storyboard',`第 ${number} 集分镜`,{source_version_id:episode.version_id,shots:invalid},'board-'+number)
  boards.push(number===1 ? await revise(board,{source_version_id:episode.version_id,shots},'correct-board') : board)
  plans.push({episode_version_id:episode.version_id,storyboard_version_id:board.version_id,target_duration_ms:number===1?6000:5000,
    bridge_note:number===2?'从岸边切入灯室':''})
}
const invalid=await create('story_bible','灯塔制作计划',{script_version_id:script.version_id,theme:'守约',world:'现代灯塔',episodes:plans,guardian:canon},'bible')
const failed=await continuity(invalid)
const blockingCodes=failed.issues.filter(issue=>issue.severity==='error').map(issue=>[issue.shot,issue.code])
assert.deepEqual(blockingCodes,[['ep1-shot2','shot_state_change'],['ep1-shot3','canon_fact_conflict']])
const draft=await revise(invalid,{...invalid.content,episodes:plans.map((item,index)=>({...item,storyboard_version_id:boards[index].version_id}))},'correct-plan')
const approved=await approve(draft,'approve')
const report=await continuity(approved)
assert.equal(report.guardian.shot_count,10)
assert(!report.issues.some(issue=>issue.severity==='error'))

const staged=[]
async function enqueue(plan,shot,image,key){
  const frames=Math.round((shot.start_ms+shot.duration_ms)*24/1000)-Math.round(shot.start_ms*24/1000)
  const [task]=await post('/generation'+path+'/still-motion',{asset_id:image.id,story_version_id:plan.version_id,shot_id:shot.shot_id,
    candidates:[{preset:'push_in',aspect:'square',frames}],idempotency_key:key})
  return task
}
for(const [index,episode] of report.episodes.entries()){
  for(const shot of episode.shots)staged.push(await enqueue(approved,shot,index?room:coast,'shot-'+shot.shot_id))
}
const rejected=[]
for(const [category,image] of defects)rejected.push([category,await enqueue(approved,report.episodes[0].shots[0],image,'injected-'+category)])
const ready=async ids=>{
  const tasks=await api('/generation'+path+'/candidates')
  if(tasks.some(task=>ids.includes(task.id) && task.status==='failed'))throw new Error(JSON.stringify(tasks.filter(task=>task.status==='failed')))
  return ids.every(id=>tasks.some(task=>task.id===id && task.status==='succeeded'))
}
await wait(()=>ready([...staged,...rejected.map(([,job])=>job)].map(job=>job.id)),'all original and injected local FFmpeg candidates',75000)

const {command,evaluate,contains,click,setField,screenshot,errors,close}=await openChrome(19241)
const appLink=(route,query={})=>base+route+'?'+new URLSearchParams({project:project.id,...query})
try {
  await command('Page.navigate',{url:appLink('/delivery/guardian',{version:invalid.version_id})})
  await wait(()=>contains('角色状态存在跳变'),'Guardian renders planned continuity evidence')
  assert(await contains('存在阻断') && await contains('剧情事实 deadline 与正史不一致'))
  await evaluate("document.querySelector('button[aria-label=\"切换主题\"]').click()")
  await wait(()=>evaluate("document.querySelector('.guardian-workbench').dataset.theme==='dark'"),'dark PRISM theme')
  assert.equal(await evaluate("getComputedStyle(document.querySelector('.guardian-toolbar select')).backgroundColor"),'rgb(27, 37, 53)')
  await screenshot('guardian-blocked.png')
  await evaluate("document.querySelector('button[aria-label=\"切换主题\"]').click()")
  await evaluate("document.querySelector('.lock-panel a').click()")
  await wait(()=>evaluate("document.activeElement.id==='guardian-shot-ep1-shot2'"),'evidence opens the exact pinned shot')

  const taskRoot=id=>'/generation/candidates/'+id
  const selection={title:'逐帧审核候选',note:'根据测试画面和镜头合同核对'}
  await command('Page.navigate',{url:appLink('/ai/candidates',{plan:approved.version_id,shot:'ep1-shot1',asset:wrongIdentity.id})})
  await wait(()=>evaluate("document.querySelectorAll('.candidate-evidence img').length===4"),'three real evidence frames and source reference')
  // The oldest original candidate is followed by four authored negative cases.
  const rejectedId=rejected[0][1].id
  assert(await evaluate(`(() => {
    const item = [...document.querySelectorAll('article.task')].find(row=>row.textContent.includes('wrong-identity'));
    if (!item) return false; item.querySelector('button').click(); return true;
  })()`))
  await wait(()=>evaluate(`document.querySelector('.candidate-evidence img[ src*="${rejectedId}/guardian-frames/1"]')?.naturalWidth>0`),'identity fixture rendered in Chrome')
  await setField('内容审核决定','rejected')
  await setField('问题类别','identity')
  await setField('问题证据帧','1')
  await setField('内容审核说明','主角脸部色块改变，与固定参考不符')
  await click('保存内容审核')
  await wait(()=>contains('候选已退回，证据已保存'),'human review decision persisted')
  await blocked(taskRoot(rejectedId)+'/select',selection,409)
  await screenshot('guardian-candidate-review.png')
  for(const [category,job] of rejected.slice(1)) {
    const verdict=await post(taskRoot(job.id)+'/guardian-review',{decision:'rejected',category,frame:1,note:'原创验收注入 · '+category})
    assert.equal(verdict.evidence.time_ms,500)
    await blocked(taskRoot(job.id)+'/select',selection,409)
  }
  for(const job of staged) {
    await post(taskRoot(job.id)+'/guardian-review',{decision:'approved',note:'脚本按预设正确画面登记人工审核决定'})
    await post(taskRoot(job.id)+'/select',{...selection,title:job.parameters.shot_id})
  }

  const edited=structuredClone(boards[1].content)
  edited.shots[4].contract.visual='左侧阿青持白信，特写必须看到信封'
  const updatedBoard=await revise(boards[1],edited,'new-shot-contract')
  const updated=await revise(approved,{...approved.content,episodes:approved.content.episodes.map((item,index)=>index ?
    {...item,storyboard_version_id:updatedBoard.version_id}:item)},'local-rework')
  const latest=await approve(updated,'local-rework-approve')
  const diff=await api(`/series/versions/${latest.version_id}/impact?baseline_version_id=${approved.version_id}`)
  assert.equal(diff.shots.filter(shot=>shot.kind==='unchanged').length,9)
  assert.deepEqual(diff.shots.filter(shot=>shot.kind==='contract_changed').map(shot=>shot.shot_id),['ep2-shot5'])
  const assembling='/timeline'+path+'/assemble'
  const assembleBody={series_version_id:latest.version_id,episode:2,profile:'square',title:'更正后第 2 集',idempotency_key:'assemble-2'}
  await blocked(assembling,assembleBody,422)
  const changed=(await continuity(latest)).episodes[1].shots[4]
  const regen=await enqueue(latest,changed,room,'rework-one')
  await wait(()=>ready([regen.id]),'one changed shot rerendered',35000)
  await post(taskRoot(regen.id)+'/guardian-review',{decision:'approved',note:'已按新合同核对信封'})
  await post(taskRoot(regen.id)+'/select',{title:'返工特写',note:'批准新的镜头版本'})
  const timelines=[await post(assembling,{...assembleBody,episode:1,title:'第 1 集',idempotency_key:'assemble-1'}),await post(assembling,assembleBody)]

  const voiceRoot='/voice'+path+'/tasks'
  const voiceJob=await post(voiceRoot,{storyboard_version_id:boards[0].version_id,series_version_id:latest.version_id,
    bindings:[{character_version_id:actor.version_id,voice:voice.name,authorization:'本机系统语音原创验收'}],idempotency_key:'guardian-voice'})
  await wait(async()=>{
    const item=(await api(voiceRoot)).find(row=>row.id===voiceJob.id)
    if(item.status==='failed')throw new Error(item.error)
    return item.status==='succeeded'
  },'real Windows offline speech and subtitles',30000)
  const [line,subtitle]=await post('/voice/tasks/'+voiceJob.id+'/select',{title:'批准配音与字幕',note:'试听验收并固定正文版本'})
  const frames=timelines[0].content.frames
  const edit=await revise(timelines[0],{...timelines[0].content,tracks:[...timelines[0].content.tracks,
    {id:'dialogue',role:'dialogue',clips:[{id:'dialogue',asset_id:line.id,at:0,frames}]},
    {id:'caption',role:'caption',clips:[{id:'caption',asset_id:subtitle.id,at:0,frames}]}]},'attach-voice')
  const runBody={plan_version_id:latest.version_id,timelines:[{number:1,timeline_version_id:edit.version_id},
    {number:2,timeline_version_id:timelines[1].version_id}],idempotency_key:'produce'}
  const run=await post('/production'+path+'/runs',runBody)
  let final
  await wait(async()=>{
    final=await api('/production/runs/'+run.id)
    if(final.status==='needs_rework')throw new Error(JSON.stringify(final.episodes))
    return final.status!=='processing'
  },'real guarded render and technical QC',50000)
  for (const episode of final.episodes.filter(item=>item.status==='needs_review')) {
    final=await post(`/production/runs/${run.id}/episodes/${episode.number}/review`,{
      expected_sha256:episode.qc.output_sha256,note:'原创验收中接受已定位的非阻断告警',idempotency_key:'episode-review',
    })
  }
  assert.equal(final.status,'passed')
  assert.equal(final.episodes[0].qc.captions.cue_count,1)
  assert.equal(final.episodes[0].qc.audio.status,'measured')

  const packagePath='/delivery'+path+'/packages'
  const packageBody={run_id:run.id,title:'Guardian 原创剧验收',platform:'local-test',region:'CN',idempotency_key:'package'}
  await blocked(packagePath,packageBody,409)
  const readiness=await api(`/delivery${path}/runs/${run.id}/readiness?platform=local-test&region=CN`)
  for(const item of readiness.blockers){
    await post('/library/assets/'+item.asset_id+'/rights',{status:'approved',source_type:'owned',holder:'原创验收样片制作者',
      evidence:'自产测试画面或本机语音录制',commercial:true,regions:['CN'],platforms:['local-test'],idempotency_key:'rights'})
  }
  const delivered=await post(packagePath,packageBody)
  let receipt
  await wait(async()=>{
    receipt=await api(packagePath+'/'+delivered.id)
    if(receipt.status==='failed')throw new Error(JSON.stringify(receipt))
    return receipt.status==='succeeded'
  },'rights-gated verified deliverable',30000)
  const file=await fetch(base+'/api/delivery/packages/'+delivered.id+'/file')
  assert.equal(file.status,200)
  const bytes=Buffer.from(await file.arrayBuffer())
  assert.equal(createHash('sha256').update(bytes).digest('hex'),receipt.sha256)
  assert(bytes.includes(Buffer.from('guardian.json')) && bytes.includes(Buffer.from('guardian-contract-v1')))

  await command('Page.navigate',{url:appLink('/delivery/guardian',{version:latest.version_id})})
  await wait(()=>contains('版本影响分析'),'current Guardian workspace')
  await setField('对比基线',approved.version_id)
  await click('比较镜头合同')
  await wait(()=>contains('ep2-shot5 · 合同变化'),'single-shot impact visible in browser')
  await screenshot('guardian-prism-light.png')
  for(const width of [1280,1440,1920]) {
    await command('Emulation.setDeviceMetricsOverride',{width,height:1000,deviceScaleFactor:1,mobile:false})
    assert(await evaluate('document.documentElement.scrollWidth<=window.innerWidth+1'))
  }
  await command('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true})
  assert(await evaluate('document.documentElement.scrollWidth<=window.innerWidth+1'))
  await screenshot('guardian-mobile.png')
  assert.deepEqual(errors,[])
  await writeFile(join(evidenceDir,'guardian-browser.json'),JSON.stringify({checked_at:new Date().toISOString(),
    episodes:2,characters:2,scenes:2,shot_count:report.guardian.shot_count,accepted_original_candidates:staged.length,
    visual_fixtures_rejected_by_recorded_review:defects.map(([category])=>category),visual_model_precision:null,visual_model_recall:null,
    detected_scripted_continuity_blockers:blockingCodes,accepted_clean_plan_has_no_blockers:true,
    rule_sample_counts:{true_positive:2,false_positive:0,false_negative:0},tested_viewport_widths:[390,1280,1440,1920],
    reused_approved_shots:9,rerendered_shots:1,voice:voice.name,checked_final_batch:run.id,
    verified_delivery_bytes:bytes.length,verified_delivery_sha256:receipt.sha256,guardian_delivery_manifest:true,
    external_paid_calls:0,javascript_errors:errors,
  },null,2)+'\n')
  console.log('Guardian Chrome: 2 episodes, 10 real approved shots, 4 rejected visual fixtures, 9 reused shots, verified ZIP.')
} catch(error) {
  console.error(await evaluate('document.body.innerText.slice(-6500)'))
  throw error
} finally { await close() }
