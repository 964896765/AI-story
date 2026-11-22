import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { copyFile, readFile, writeFile } from 'node:fs/promises'
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
async function artwork(name,{background='0x20445c',face='0xffc79a',coat='0x2ddd9a',subject=true,black=false}={}) {
  const filename=join(qaRoot,name+'.png')
  const shapes=[`drawbox=x=0:y=130:w=320:h=110:color=${background}:t=fill`,
    'drawbox=x=197:y=58:w=45:h=52:color=0xdfa582:t=fill','drawbox=x=179:y=110:w=80:h=100:color=0x5b4296:t=fill']
  if(subject)shapes.push(`drawbox=x=78:y=60:w=49:h=52:color=${face}:t=fill`,
    `drawbox=x=62:y=111:w=82:h=95:color=${coat}:t=fill`,'drawbox=x=44:y=138:w=26:h=18:color=white:t=fill')
  const filter = black ? ['color=black:s=320x240'] : ['testsrc2=size=320x240','-vf',shapes.join(',')]
  execFileSync('ffmpeg',['-v','error','-f','lavfi','-i',...filter,
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
const blackArtwork=await artwork('technical-black',{black:true})
const ocr=(await api('/analysis/capabilities')).capabilities.find(item=>item.id==='ocr')
assert(ocr?.available && ocr.languages.includes('zh-Hans-CN'),'Installed Chinese OCR is required')
await copyFile(join(process.env.SystemRoot || 'C:/Windows','Fonts','simhei.ttf'),join(qaRoot,'guardian-ocr-font.ttf'))
async function sign(name,text) {
  const filename=name+'.png'
  execFileSync('ffmpeg',['-v','error','-f','lavfi','-i','color=white:s=960x960','-vf',
    `drawtext=fontfile=guardian-ocr-font.ttf:text='${text}':fontsize=130:fontcolor=black:x=(w-tw)/2:y=(h-th)/2`,
    '-frames:v','1','-threads','1',filename],{cwd:qaRoot,timeout:15000})
  const body=new FormData()
  body.set('file',new Blob([await readFile(join(qaRoot,filename))]),filename)
  body.set('authorization','本机 FFmpeg 自制牌匾文字，供验收')
  return api(path+'/assets',{method:'POST',body})
}
const correctSign=await sign('correct-sign','灯塔坐标')
const wrongSign=await sign('wrong-sign','旧版标识')
const installed=(await api('/voice/capabilities')).voices
const voice=installed.find(item=>item.locale==='zh-CN')
assert(voice,'Chinese Windows offline voice is required for this acceptance')
const speech=(await api('/analysis/capabilities')).capabilities.find(item=>item.id==='asr')
assert(speech?.available && speech.languages.includes('zh-CN'),'Mandarin desktop dictation is required')
const novel=await create('novel','灯塔交信',{text:'阿青和守塔人在岸边见面，带着旧信进入灯室。',authorization:'原创验收剧'},'novel')
const dialogue='大家好，欢迎来到灯塔。'
const script=await create('script','灯塔交信 · 剧本',{body:'日落前交信。阿青说「'+dialogue+'」',source_version_id:novel.version_id},'script')
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
    planned_duration:number===1 && index===4 ? 5 : 1,scene_version_id:scene.version_id,character_version_ids:ids,strategy:'still_motion',
    contract:{visual:'左侧阿青持白信，右侧是守塔人',facts:{deadline:'日落前交信'},opening:structuredClone(states),closing:structuredClone(states),
      source_image_asset_ids:[art.id,...(number===1 && index===0 ? [...defects.map(([,image])=>image.id),blackArtwork.id]:[])]},
  }))
  if(number===1)Object.assign(shots[4],{dialogue,dialogue_ms:3900,speaker_version_id:actor.version_id})
  const invalid=structuredClone(shots)
  if(number===1){
    invalid[1].contract.opening[0].left_hand=null
    invalid[1].contract.opening[0].right_hand='letter'
    invalid[1].contract.opening[0].action='奔跑'
    invalid[2].contract.facts.deadline='午夜交信'
  }
  const board=await create('storyboard',`第 ${number} 集分镜`,{source_version_id:episode.version_id,shots:invalid},'board-'+number)
  boards.push(number===1 ? await revise(board,{source_version_id:episode.version_id,shots},'correct-board') : board)
  plans.push({episode_version_id:episode.version_id,storyboard_version_id:board.version_id,target_duration_ms:number===1?9000:5000,
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
const technical=await enqueue(approved,report.episodes[0].shots[0],blackArtwork,'injected-technical-black')
const ready=async ids=>{
  const tasks=await api('/generation'+path+'/candidates')
  if(tasks.some(task=>ids.includes(task.id) && task.status==='failed'))throw new Error(JSON.stringify(tasks.filter(task=>task.status==='failed')))
  return ids.every(id=>tasks.some(task=>task.id===id && task.status==='succeeded'))
}
await wait(()=>ready([...staged,...rejected.map(([,job])=>job),technical].map(job=>job.id)),'all original and injected local FFmpeg candidates',75000)

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
  await command('Page.navigate',{url:appLink('/ai/candidates',{plan:approved.version_id,shot:'ep1-shot1',asset:blackArtwork.id,candidate:technical.id})})
  await wait(()=>evaluate("document.querySelector('[data-testid=visual-check-status]')?.textContent.trim()==='技术检查阻断'"),'black candidate blocked in Chrome')
  const result=(await api('/generation'+path+'/candidates')).find(item=>item.id===technical.id)
  const visual=result.output.guardian_visual
  const point=visual.findings[0].evidence
  assert.equal(visual.output_sha256,result.output.sha256)
  assert.equal(visual.black_frames,24)
  assert.equal(visual.findings[0].code,'black_output')
  await click('定位证据')
  await wait(()=>evaluate(`Math.abs(document.querySelector('video[aria-label="当前候选"]').currentTime-${point.time_ms/1000})<0.05`),'locates the actual evidence frame')
  assert(await evaluate("Array.from(document.querySelectorAll('.content-review option')).some(item=>item.value==='approved' && item.disabled)"))
  await blocked(taskRoot(technical.id)+'/guardian-review',{decision:'approved',note:'尝试通过黑场'},409)
  await blocked(taskRoot(technical.id)+'/select',selection,409)
  await screenshot('guardian-visual-blocked.png')
  await setField('内容审核说明','候选逐帧检测为全黑，退回重做')
  await click('保存内容审核')
  await wait(()=>contains('候选已退回，证据已保存'),'blocked candidate rejection persisted')
  const rejectedBlack=(await api('/generation'+path+'/candidates')).find(item=>item.id===technical.id)
  assert.equal(rejectedBlack.output.guardian_review.evidence.sha256,point.sha256)
  for(const job of staged) {
    await post(taskRoot(job.id)+'/guardian-review',{decision:'approved',note:'脚本按预设正确画面登记人工审核决定'})
    await post(taskRoot(job.id)+'/select',{...selection,title:job.parameters.shot_id})
  }

  const assembling='/timeline'+path+'/assemble'
  const originalTimeline=await post(assembling,{series_version_id:approved.version_id,episode:2,
    title:'第 2 集时间轴',profile:'square',idempotency_key:'before-shot-rework'})
  await command('Page.navigate',{url:appLink('/creative/storyboard',{version:boards[1].version_id,shot:'ep2-shot5'})})
  await wait(()=>evaluate("document.activeElement.id==='guardian-shot-ep2-shot5'"),'latest storyboard shot opens for contract edit')
  await evaluate(`(() => {
    const contract=document.querySelector('#guardian-shot-ep2-shot5 .shot-contract');
    contract.open=true;
    const source=contract.querySelector('select[multiple]');
    for (const option of source.options) option.selected=${JSON.stringify([correctSign.id,wrongSign.id])}.includes(option.value);
    source.dispatchEvent(new Event('change',{bubbles:true}));
    Array.from(contract.querySelectorAll('button')).find(button=>button.textContent.trim()==='添加画面文字规则').click();
  })()`)
  await setField('必现文字 1','灯塔坐标')
  await click('添加禁现文字')
  await setField('禁现文字 1','旧版标识')
  await setField('本次版本说明','为第五镜锁定牌匾文字')
  await click('保存新版本')
  await wait(()=>contains('已保存数据库版本 v2'),'screen text contract saved in immutable storyboard')
  const [boardHead]=await api('/story/entities/'+boards[1].id+'/versions')
  const updatedBoard=await api('/story/versions/'+boardHead.version_id)
  assert.deepEqual(updatedBoard.content.shots[4].contract.screen_text,
    {language:'zh-Hans-CN',required:['灯塔坐标'],forbidden:['旧版标识']})
  assert(!boards[1].content.shots[4].contract.screen_text)
  const updated=await revise(approved,{...approved.content,episodes:approved.content.episodes.map((item,index)=>index ?
    {...item,storyboard_version_id:updatedBoard.version_id}:item)},'local-rework')
  const latest=await approve(updated,'local-rework-approve')
  const diff=await api(`/series/versions/${latest.version_id}/impact?baseline_version_id=${approved.version_id}`)
  assert.equal(diff.shots.filter(shot=>shot.kind==='unchanged').length,9)
  assert.deepEqual(diff.shots.filter(shot=>shot.kind==='contract_changed').map(shot=>shot.shot_id),['ep2-shot5'])
  const assembleBody={series_version_id:latest.version_id,episode:2,profile:'square',title:'更正后第 2 集',idempotency_key:'assemble-2'}
  await blocked(assembling,assembleBody,422)
  await command('Page.navigate',{url:appLink('/delivery/guardian',{version:latest.version_id})})
  await wait(()=>contains('版本影响分析'),'approved Guardian rework workspace')
  await setField('对比基线',approved.version_id)
  await click('比较镜头合同')
  await click('定位镜头 ep2-shot5')
  await wait(()=>evaluate("document.activeElement.value==='ep2-shot5'"),'locate changed shot')
  await evaluate("document.querySelector('.rework-actions summary').click()")
  await setField('返工画幅','square')
  await setField('返工运镜','pull_out')
  await setField('返工参考图',correctSign.id)
  await setField('返工原因','按新版合同核对灯塔坐标')
  await click('提交单镜头返工')
  await wait(()=>contains('按新版合同核对灯塔坐标'),'rework reason persisted')
  const [regen]=await api('/generation'+path+'/candidates?shot_id=ep2-shot5&series_id='+latest.id)
  assert.equal(regen.rework.reason,'按新版合同核对灯塔坐标')
  assert.equal(regen.story_version_id,latest.version_id)
  assert.equal(regen.parameters.frames,24)
  const latestShot=(await continuity(latest)).episodes[1].shots[4]
  const wrong=await enqueue(latest,latestShot,wrongSign,'screen-text-mismatch')
  await wait(()=>ready([regen.id,wrong.id]),'both actual OCR candidates produced',35000)
  const inspected=await api('/generation'+path+'/candidates?shot_id=ep2-shot5&series_id='+latest.id)
  const matched=inspected.find(item=>item.id===regen.id).output.guardian_screen_text
  const mismatch=inspected.find(item=>item.id===wrong.id).output.guardian_screen_text
  assert.equal(matched.status,'matched',JSON.stringify(matched))
  assert.equal(matched.adapter.language,'zh-Hans-CN')
  assert(matched.samples.every(item=>item.lines.some(line=>line.replace(/\s/g,'').includes('灯塔坐标'))))
  assert.equal(mismatch.status,'review')
  assert.deepEqual(mismatch.findings.map(item=>item.code),['required_not_seen','forbidden_seen'])
  await command('Page.navigate',{url:appLink('/ai/candidates',{plan:latest.version_id,shot:'ep2-shot5',asset:wrongSign.id,candidate:wrong.id})})
  await wait(()=>evaluate("document.querySelector('[data-testid=screen-text-status]')?.textContent.trim()==='文字发现待人工核验'"),'actual OCR discrepancy in Chrome')
  await setField('内容审核说明','采样发现错误的牌匾文字')
  assert(await evaluate("document.querySelector('.content-review button').disabled"))
  await blocked(taskRoot(wrong.id)+'/guardian-review',{decision:'approved',note:'尝试跳过人工文字确认'},409)
  await evaluate("document.querySelector('.screen-check details').open=true")
  await click('定位文字证据 0.500 秒')
  await wait(()=>evaluate("Math.abs(document.querySelector('video[aria-label=当前候选]').currentTime-0.5)<0.05"),'seek to the actual OCR evidence')
  await evaluate("document.querySelector('.screen-check').scrollIntoView({block:'center'})")
  await screenshot('guardian-screen-text.png')
  await setField('内容审核决定','rejected')
  await setField('问题类别','screen_text')
  await setField('问题证据帧','1')
  await click('保存内容审核')
  await wait(()=>contains('候选已退回，证据已保存'),'wrong sign rejected with timestamped evidence')
  const applyPath='/timeline'+path+'/shot-replacements'
  const replaceBody={series_version_id:latest.version_id,timeline_version_id:originalTimeline.version_id,
    shot_id:'ep2-shot5',candidate_id:regen.id,note:'确认只替换第五镜',idempotency_key:'blocked-unreviewed'}
  await blocked(applyPath,replaceBody,409)
  const followLink=label=>evaluate(`Array.from(document.querySelectorAll('a')).find(a=>a.textContent.trim()===${JSON.stringify(label)})?.click()`)
  await command('Page.navigate',{url:appLink('/ai/candidates',{plan:latest.version_id,shot:'ep2-shot5',asset:correctSign.id,candidate:regen.id})})
  await wait(()=>evaluate(`document.querySelector('.candidate-evidence img[src*="${regen.id}/guardian-frames/1"]')?.naturalWidth>0`),'exact rework candidate evidence')
  await setField('内容审核说明','按新合同核对画面和信封')
  await click('保存内容审核')
  await wait(()=>contains('内容审核已保存，可以采纳'),'rework review persisted')
  await blocked(applyPath,replaceBody,409)
  await setField('素材标题','返工特写')
  await setField('采纳说明','批准新的镜头版本')
  await click('采纳为视频素材')
  await wait(()=>contains('已采纳 返工特写'),'replacement candidate adopted')
  await followLink('返回镜头返工')
  await click('将已采纳候选用于时间轴')
  await wait(()=>evaluate(`Array.from(document.querySelectorAll('.rework-actions select option')).some(option=>option.value===${JSON.stringify(originalTimeline.version_id)})`),'baseline timeline is selectable')
  await setField('返工基线时间轴',originalTimeline.version_id)
  await setField('替换说明','确认只替换第五镜')
  await click('保存单镜头替换版本')
  await wait(()=>contains('已保存时间轴 v2'),'new timeline version saved')
  await screenshot('guardian-shot-rework.png')
  const [versionEntry]=await api('/story/entities/'+originalTimeline.id+'/versions')
  const replacement=await api('/story/versions/'+versionEntry.version_id)
  const before=originalTimeline.content.tracks[0].clips, after=replacement.content.tracks[0].clips
  assert.deepEqual(after.slice(0,4),before.slice(0,4))
  assert.notEqual(after[4].asset_id,before[4].asset_id)
  assert.deepEqual({...after[4],asset_id:before[4].asset_id},before[4])
  assert.deepEqual((await api('/story/versions/'+originalTimeline.version_id)).content,originalTimeline.content)
  assert.equal(replacement.provenance.shot_replacement.request.candidate_id,regen.id)
  await blocked(applyPath,{...replaceBody,idempotency_key:'blocked-stale-timeline'},409)
  const timelines=[await post(assembling,{...assembleBody,episode:1,title:'第 1 集',idempotency_key:'assemble-1'}),replacement]

  const voiceRoot='/voice'+path+'/tasks'
  const voiceBody={storyboard_version_id:boards[0].version_id,series_version_id:latest.version_id,
    bindings:[{character_version_id:actor.version_id,voice:voice.name,authorization:'本机系统语音原创验收'}],idempotency_key:'guardian-voice'}
  const voiceJob=await post(voiceRoot,voiceBody)
  const otherVoice=await post(voiceRoot,{...voiceBody,idempotency_key:'different-voice-timing',
    bindings:[{...voiceBody.bindings[0],rate:1}]})
  for(const job of [voiceJob,otherVoice]) {
    await wait(async()=>{
      const item=(await api(voiceRoot)).find(row=>row.id===job.id)
      if(item.status==='failed')throw new Error(item.error)
      return item.status==='succeeded'
    },'real Windows offline speech and subtitles',30000)
  }
  const [line,subtitle]=await post('/voice/tasks/'+voiceJob.id+'/select',{title:'批准配音与字幕',note:'试听验收并固定正文版本'})
  const [,otherSubtitle]=await post('/voice/tasks/'+otherVoice.id+'/select',{title:'第二种配音时长',note:'验证混用另一配音任务会失败'})
  const frames=timelines[0].content.frames
  const edit=await revise(timelines[0],{...timelines[0].content,tracks:[...timelines[0].content.tracks,
    {id:'dialogue',role:'dialogue',clips:[{id:'dialogue',asset_id:line.id,at:0,frames}]},
    {id:'caption',role:'caption',clips:[{id:'caption',asset_id:subtitle.id,at:0,frames}]}]},'attach-voice')
  const runBody={plan_version_id:latest.version_id,timelines:[{number:1,timeline_version_id:edit.version_id},
    {number:2,timeline_version_id:timelines[1].version_id}],policy:{dialogue_asr_language:'zh-CN'},idempotency_key:'produce'}
  const mixed=await create('timeline','混用配音与字幕', {...edit.content,tracks:edit.content.tracks.map(track=>track.role==='caption'?
    {...track,clips:[{...track.clips[0],asset_id:otherSubtitle.id}]}:track)},'wrong-voice-pair')
  await blocked('/production'+path+'/runs',{...runBody,timelines:[{number:1,timeline_version_id:mixed.version_id},runBody.timelines[1]],
    idempotency_key:'mixed-pair-must-fail'},422)
  await command('Page.navigate',{url:appLink('/production')})
  await wait(()=>evaluate(`!!document.querySelector('.production select option[value="${latest.version_id}"]')`),'approved plan in production form')
  await evaluate("document.querySelector('.production > details').open=true; document.querySelector('.quality-rules').open=true")
  await setField('已批准制作计划',latest.version_id)
  await wait(()=>evaluate(`document.querySelectorAll('.production select option[value="${edit.version_id}"]').length===2`),'fixed timelines in production form')
  await setField('第 1 集 · 第 1 集',edit.version_id)
  await setField('第 2 集 · 第 2 集',timelines[1].version_id)
  await wait(()=>evaluate("!!document.querySelector('.quality-rules select option[value=\"zh-CN\"]')"),'installed recognition option')
  await setField('对白听写语言','zh-CN')
  await click('提交渲染和质检')
  let run
  await wait(async()=>{
    const runs=await api('/production'+path+'/runs')
    run=runs[0]
    return !!run
  },'submitted batch in production queue')
  assert.equal(run.policy.dialogue_asr_language,'zh-CN')
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
  const dialogueReport=final.episodes[0].qc.dialogue
  assert.equal(dialogueReport.recognition.adapter.language,'zh-CN')
  assert.equal(dialogueReport.lines[0].caption_status,'matched')
  assert.equal(dialogueReport.lines[0].audio_status,'signal')
  assert(dialogueReport.lines[0].recognition.observed.length>0,JSON.stringify(dialogueReport))
  await command('Page.navigate',{url:appLink('/production',{run:run.id,episode:1})})
  await wait(()=>contains('固定对白核验'),'dialogue QC appears in production')
  await evaluate("document.querySelector('.dialogue-report').open=true")
  await click('回听 4.000 秒')
  await wait(()=>evaluate("Math.abs(document.querySelector('.review-preview video').currentTime-4)<0.1"),'published dialogue evidence seeks correctly')
  await evaluate("document.querySelector('.dialogue-report').scrollIntoView({block:'center'})")
  await screenshot('guardian-dialogue-review.png')

  const mute=await create('timeline','故意静音的对白', {...edit.content,tracks:edit.content.tracks.map(track=>track.role==='dialogue'?
    {...track,volume:0}:track)},'muted-dialogue-fixture')
  const muted=await post('/production'+path+'/runs',{...runBody,previous_run_id:run.id,timelines:[{number:1,timeline_version_id:mute.version_id}],
    idempotency_key:'mute-check'})
  let mutedResult
  await wait(async()=>{
    mutedResult=await api('/production/runs/'+muted.id)
    return mutedResult.status!=='processing'
  },'muted dialogue renders and fails QC',50000)
  assert.equal(mutedResult.status,'needs_rework')
  assert.equal(mutedResult.episodes[0].render_status,'succeeded')
  assert(mutedResult.episodes[0].qc.issues.some(item=>item.code==='dialogue_silent'&&item.severity==='error'&&item.start_ms===4000))
  assert(mutedResult.episodes[0].qc.issues.some(item=>item.code==='dialogue_track_muted'&&item.severity==='error'))
  assert.equal(mutedResult.episodes[1].render_task_id,final.episodes[1].render_task_id)
  await blocked(`/production/runs/${muted.id}/episodes/1/review`,{
    expected_sha256:mutedResult.episodes[0].qc.output_sha256,note:'不能通过静音',idempotency_key:'mute-review'},409)

  const bedFile=join(qaRoot,'guardian-music.wav')
  execFileSync('ffmpeg',['-v','error','-f','lavfi','-i','sine=frequency=630:sample_rate=48000:duration=9',
    '-af','volume=3',bedFile],{timeout:15000})
  const bedUpload=new FormData()
  bedUpload.set('file',new Blob([await readFile(bedFile)]),'原创验收背景音.wav')
  bedUpload.set('authorization','本机生成的测试音')
  const bed=await api(path+'/assets',{method:'POST',body:bedUpload})
  const withBed=await create('timeline','疑似盖住对白的混音',{...edit.content,tracks:[...edit.content.tracks,
    {id:'music',role:'music',volume:0.25,clips:[{id:'loud-bed',asset_id:bed.id,at:0,frames}]}]},'overpowering-music')
  const masking=await post('/production'+path+'/runs',{...runBody,previous_run_id:run.id,
    timelines:[{number:1,timeline_version_id:withBed.version_id}],idempotency_key:'check-dialogue-balance'})
  let maskingResult
  await wait(async()=>{
    maskingResult=await api('/production/runs/'+masking.id)
    return maskingResult.status!=='processing'
  },'actual mix quality report',55000)
  const affected=maskingResult.episodes[0]
  assert.equal(maskingResult.status,'needs_review',JSON.stringify(affected))
  const maskingIssue=affected.qc.issues.find(issue=>issue.code==='dialogue_background_masking')
  assert(maskingIssue,'deliberately strong background should require review: '+JSON.stringify(affected.qc))
  assert.deepEqual(maskingIssue.clips,['dialogue','loud-bed'])
  const flaggedBalance=affected.qc.dialogue.lines[0].balance
  assert.equal(flaggedBalance.status,'review')
  assert(flaggedBalance.margin_db<6 && maskingIssue.end_ms-maskingIssue.start_ms>=300)
  await command('Page.navigate',{url:appLink('/production',{run:masking.id,episode:1})})
  await wait(()=>contains('第 5 镜的背景声可能盖住对白'),'auditable masking finding in production')
  await evaluate("document.querySelector('.dialogue-report').open=true")
  await click(`回听混音 ${(maskingIssue.start_ms/1000).toFixed(3)} 秒`)
  await wait(()=>evaluate(`Math.abs(document.querySelector('.review-preview video')?.currentTime-${maskingIssue.start_ms/1000})<0.1`),
    'actual final mix seeks to measured range')
  await evaluate("document.querySelector('.dialogue-report').scrollIntoView({block:'center'})")
  await screenshot('guardian-dialogue-balance.png')
  await click('定位关联片段 2')
  await wait(()=>evaluate("document.activeElement?.dataset.clipId==='loud-bed'"),'background clip focused in timeline')
  await evaluate(`Array.from(document.querySelectorAll('.timeline-settings label')).find(label=>
    label.textContent.trim()==='对白时压低配乐').querySelector('input').click()`)
  await click('保存时间轴版本')
  await wait(()=>contains('时间轴 v2 已保存'),'balance correction saved as new timeline')
  const fixedMix=(await api(path+'/story/entities?kind=timeline')).items.find(item=>item.id===withBed.id)
  assert.equal(fixedMix.version,2)
  const fixedTimeline=await api('/story/versions/'+fixedMix.version_id)
  assert.equal(fixedTimeline.content.music_ducking,true)
  assert.equal(fixedTimeline.content.tracks.find(track=>track.role==='music').volume,0.25)
  await evaluate("document.querySelector('.timeline-settings').scrollIntoView({block:'center'})")
  await screenshot('guardian-ducking-settings.png')
  await click('返回原质检批次')
  await wait(()=>contains('第 5 镜的背景声可能盖住对白'),'original quality evidence preserved')
  await click('按此批次局部返工')
  await wait(()=>evaluate(`!!document.querySelector('.production select option[value="${fixedMix.version_id}"]')`),'fixed timeline available for rework')
  await setField('第 1 集 · 第 1 集',fixedMix.version_id)
  await click('提交渲染和质检')
  let balanced
  await wait(async()=>{
    const batches=await api('/production'+path+'/runs')
    const repair=batches.find(item=>item.previous_run_id===masking.id)
    if(!repair || repair.status==='processing') return false
    balanced=await api('/production/runs/'+repair.id)
    return true
  },'actual adjusted mix and targeted QC',55000)
  const adjusted=balanced.episodes[0]
  const clearedBalance=adjusted.qc?.dialogue?.lines[0]?.balance
  assert.equal(adjusted.qc?.music_ducking?.preset,'ffmpeg-sidechain-dialogue-v1')
  assert.equal(adjusted.qc?.music_ducking?.status,'applied')
  assert.equal(clearedBalance?.status,'clear',JSON.stringify(adjusted))
  assert.equal(balanced.episodes[1].qc_task_id,maskingResult.episodes[1].qc_task_id)
  assert.equal((await api('/production/runs/'+masking.id)).status,'needs_review')
  if(balanced.status==='needs_review') {
    balanced=await post(`/production/runs/${balanced.id}/episodes/1/review`,{
      expected_sha256:adjusted.qc.output_sha256,note:'已核对白期间自动压低配乐后的成片和其他非阻断告警',idempotency_key:'balanced-episode-review',
    })
  }
  assert.equal(balanced.status,'passed')

  const packagePath='/delivery'+path+'/packages'
  const packageBody={run_id:balanced.id,title:'Guardian 原创剧验收',platform:'local-test',region:'CN',idempotency_key:'package'}
  await blocked(packagePath,{...packageBody,run_id:muted.id,idempotency_key:'mute-delivery'},409)
  await blocked(packagePath,{...packageBody,run_id:masking.id,idempotency_key:'unreviewed-mix-delivery'},409)
  await blocked(packagePath,packageBody,409)
  const readiness=await api(`/delivery${path}/runs/${balanced.id}/readiness?platform=local-test&region=CN`)
  assert(!readiness.blockers.some(item=>item.asset_id===before[4].asset_id),'replaced clip is outside delivery rights scope')
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
  assert(bytes.includes(Buffer.from('guardian-visual-luma-v1')))
  assert(bytes.includes(Buffer.from('guardian-screen-text-v1')))
  assert(bytes.includes(Buffer.from('guardian-dialogue-v1')))
  assert(bytes.includes(Buffer.from('guardian-dialogue-balance-v1')))
  assert(bytes.includes(Buffer.from('ffmpeg-sidechain-dialogue-v1')))

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
    technical_black_fixture:{task_id:technical.id,checked_frames:visual.checked_frames,black_frames:visual.black_frames,
      issue:visual.findings[0],human_approval_blocked:true,rejection_preserved:true},
    detected_scripted_continuity_blockers:blockingCodes,accepted_clean_plan_has_no_blockers:true,
    rule_sample_counts:{true_positive:2,false_positive:0,false_negative:0},tested_viewport_widths:[390,1280,1440,1920],
    reused_approved_shots:9,rerendered_shots:1,voice:voice.name,checked_final_batch:balanced.id,
    screen_text:{matched,mismatch,explicit_review_gate:true,contract_saved_in_browser:true,export_included:true},
    dialogue:{report:dialogueReport,mixed_pair_blocked:true,muted_qc:mutedResult.episodes[0].qc.dialogue,
      muted_delivery_blocked:true,unchanged_episode_reused:true},
    dialogue_balance:{flagged:flaggedBalance,finding:maskingIssue,corrected:clearedBalance,
      historical_timeline_version:withBed.version_id,corrected_timeline_version:fixedMix.version_id,
      focused_music_clip_in_browser:true,exact_preview_seek:true,unreviewed_delivery_blocked:true,
      unaffected_episode_qc_reused:true,verified_zip_contains_balance_report:true},
    music_ducking:{...adjusted.qc.music_ducking,checked_in_browser:true,unchanged_music_track_gain:0.25,
      balance_clear:clearedBalance.status==='clear',verified_zip_contains_preset:true},
    shot_rework:{task_id:regen.id,old_timeline:originalTimeline.version_id,new_timeline:replacement.version_id,
      unchanged_clips_in_affected_episode:4,original_timeline_preserved:true},
    verified_delivery_bytes:bytes.length,verified_delivery_sha256:receipt.sha256,guardian_delivery_manifest:true,
    external_paid_calls:0,javascript_errors:errors,
  },null,2)+'\n')
  console.log('Guardian Chrome: 2 episodes, 10 real approved shots, 4 rejected visual fixtures, 9 reused shots, verified ZIP.')
} catch(error) {
  console.error(await evaluate('document.body.innerText.slice(-6500)'))
  throw error
} finally { await close() }
