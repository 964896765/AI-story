import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { readFile, writeFile } from 'node:fs/promises'
import { join } from 'node:path'
import { api, base, evidenceDir, openChrome, post, qaRoot, wait } from './chrome-qa.mjs'

await wait(async()=>{
  try {return (await api('/health')).ready && (await api('/queue')).workers.some(worker=>worker.online)}
  catch {return false}
},'isolated specification services')
const project=await post('/projects',{name:'制作规格验收 · 港灯'})
const other=await post('/projects',{name:'制作规格隔离项目'})
const root='/projects/'+project.id
const specs=root+'/production-specs'
const create=(kind,title,content,idempotency_key)=>post(root+'/story/entities',{kind,title,content,idempotency_key})
const link=(route,query={})=>base+route+'?'+new URLSearchParams({project:project.id,...query})
async function blocked(route,body,status,reason) {
  const response=await fetch(base+'/api'+route,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})
  const detail=await response.json()
  assert.equal(response.status,status,JSON.stringify(detail))
  if(reason)assert(JSON.stringify(detail).includes(reason),JSON.stringify(detail))
}

const {command,evaluate,contains,click,setField,screenshot,errors,close}=await openChrome(19245)
try {
  const note='旧浏览器备注 · 只在试制库验证'
  await command('Page.navigate',{url:link('/wizard',{step:1})})
  await wait(()=>contains('当前项目尚未保存制作规格'),'fresh project')
  await evaluate(`localStorage.setItem(${JSON.stringify('ai-story:wizard:'+project.id)},${JSON.stringify(JSON.stringify({0:note}))})`)
  await command('Page.reload')
  await wait(()=>contains('复制本机备注到规格草稿'),'historic browser note detected')
  await click('复制本机备注到规格草稿')
  await click('保存规格新版本')
  await wait(()=>contains('已保存规格 v1'),'incomplete specification recorded')
  const [{id:draftId}]=(await api(specs)).items
  assert((await api(specs+'/'+draftId)).missing_fields.includes('episode_count'))

  const currentArt=join(qaRoot,'spec-art.png')
  execFileSync('ffmpeg',['-v','error','-f','lavfi','-i','testsrc2=size=256x256','-frames:v','1','-threads','1',currentArt],{timeout:15000})
  const file=new FormData()
  file.set('file',new Blob([await readFile(currentArt)]),'spec-art.png')
  file.set('authorization','自制 FFmpeg 测试图')
  const image=await api(root+'/assets',{method:'POST',body:file})
  const style='平面线稿'
  const canon={facts:{light:'港灯点亮'},character_version_ids:[],scene_version_ids:[],style:{description:style}}
  const script=await create('script','港灯剧本',{body:'港灯点亮。'},'script')
  const episode=await create('episode','港灯第一集',{number:1,body:'港灯点亮。',source_version_id:script.version_id},'episode')
  const scene=await create('scene','港口',{location:'旧港'},'scene')
  canon.scene_version_ids.push(scene.version_id)
  const shot={number:1,shot_id:'pilot-shot',description:'港灯',planned_duration:1.5,scene_version_id:scene.version_id,
    strategy:'still_motion',contract:{visual:'旧港的灯',source_image_asset_ids:[image.id]}}
  const incompleteBoard=await create('storyboard','待核规格分镜',{source_version_id:episode.version_id,shots:[shot],
    production_spec_version_id:draftId},'incomplete-board')
  const bible=(board,id)=>({production_spec_version_id:id,script_version_id:script.version_id,theme:'港灯',world:'旧港',
    episodes:[{episode_version_id:episode.version_id,storyboard_version_id:board.version_id,target_duration_ms:1500}],guardian:canon})
  const incomplete=await create('story_bible','不完整规格计划',bible(incompleteBoard,draftId),'incomplete-plan')
  const approve=(id,edition)=>({expected_version:edition.version,note:'检查固定制作规格',idempotency_key:id})
  await blocked('/series/entities/'+incomplete.id+'/approve',approve('incomplete',incomplete),422,'production_spec_incomplete')

  await setField('计划集数','1')
  await setField('单集目标时长（毫秒）','1500')
  await setField('画风与美术',style)
  await setField('画幅','square')
  await setField('发行平台标识','local-test')
  await click('保存规格新版本')
  await wait(()=>contains('已保存规格 v2'),'complete specification ready')
  const [fixed]=(await api(specs)).items
  assert.deepEqual(fixed.missing_fields,[])
  await command('Page.reload')
  await wait(()=>evaluate(`document.querySelector('.spec-center .hash')?.textContent===${JSON.stringify(fixed.sha256)}`),'same hash after browser reload')
  assert.equal((await api('/projects/'+other.id+'/production-specs')).items.length,0)
  await screenshot('production-spec-center.png')

  const board=await create('storyboard','港灯分镜',{source_version_id:episode.version_id,shots:[shot],
    production_spec_version_id:fixed.id},'board')
  const plan=await create('story_bible','港灯制作计划',bible(board,fixed.id),'plan')
  const continuity='/series/versions/'+plan.version_id+'/continuity'
  const report=await api(continuity)
  assert.equal(report.ready_for_review,true,JSON.stringify(report.issues))
  const approved=await post('/series/entities/'+plan.id+'/approve',approve('approved',plan))
  const approvedPath='/series/versions/'+approved.version_id+'/continuity'
  const firstHash=(await api(approvedPath)).guardian.contracts['pilot-shot']

  await setField('画幅','portrait')
  await click('保存规格新版本')
  await wait(()=>contains('已保存规格 v3'),'different aspect saved as a new version')
  const [newer]=(await api(specs)).items
  assert.equal(newer.settings.profile,'portrait')
  const imageRoute='/generation'+root+'/images'
  const keyframe={spec_version_id:fixed.id,source_version_id:approved.version_id,shot_id:'pilot-shot',
    prompt:'港灯关键帧验收',idempotency_key:'fixed-keyframe'}
  await blocked(imageRoute,{...keyframe,spec_version_id:newer.id},422,'不一致')
  const queuedKeyframe=await post(imageRoute,keyframe)
  let renderedKeyframe
  await wait(async()=>{
    renderedKeyframe=(await api(imageRoute)).find(item=>item.id===queuedKeyframe.id)
    if (renderedKeyframe?.status==='failed') throw new Error(JSON.stringify(renderedKeyframe))
    return renderedKeyframe?.status==='succeeded'
  },'actual image decode for fixed approved shot')
  assert.equal(renderedKeyframe.source.contract_sha256,firstHash)
  assert.equal(renderedKeyframe.references[0].id,image.id)
  assert.equal(renderedKeyframe.output.width,1024)
  const mixed=await create('story_bible','混用规格的计划',bible(board,newer.id),'mixed-plan')
  await blocked('/series/entities/'+mixed.id+'/approve',approve('mixed',mixed),422,'production_spec_storyboard')
  await click('比较规格与影响')
  await wait(()=>contains('可能受影响'),'impact of the new aspect')
  const diff=await api(specs+'/compare?'+new URLSearchParams({left:fixed.id,right:newer.id}))
  assert(diff.affected_modules.includes('Guardian'))
  assert(diff.pinned_references.story_bible>=2 && diff.pinned_references.storyboard>=1)
  await screenshot('production-spec-impact.png')
  await setField('查看规格版本',fixed.id)
  await click('恢复历史规格')
  await click('确认恢复为新版本')
  await wait(()=>contains('已恢复为规格 v4'),'append-only restore')
  const [restored]=(await api(specs)).items
  assert.equal(restored.sha256,fixed.sha256)
  assert.notEqual(restored.id,fixed.id)
  assert.equal(restored.settings.imported_note,note)
  assert((await evaluate(`localStorage.getItem(${JSON.stringify('ai-story:wizard:'+project.id)})`)).includes(note))
  const processCheck="from fastapi.testclient import TestClient; from app.main import app; import sys; response=TestClient(app).get(sys.argv[1]); assert response.status_code==200 and response.json()['sha256']==sys.argv[2]"
  execFileSync(process.env.AI_STORY_QA_PYTHON,['-c',processCheck,'/api'+specs+'/'+restored.id,restored.sha256],{cwd:'backend',timeout:15000})
  assert.equal((await api(approvedPath)).guardian.contracts['pilot-shot'],firstHash)
  await command('Page.navigate',{url:link('/creative/storyboard',{version:board.version_id})})
  await wait(()=>contains('固定制作规格 v2'),'storyboard opens its historical specification')

  const candidatePath='/generation'+root+'/still-motion'
  const request={asset_id:image.id,story_version_id:approved.version_id,shot_id:'pilot-shot',
    candidates:[{preset:'push_in',aspect:'square',frames:36}],idempotency_key:'candidate'}
  await blocked(candidatePath,{...request,candidates:[{...request.candidates[0],aspect:'portrait'}]},422,'画幅')
  const [candidate]=await post(candidatePath,request)
  assert.equal(candidate.production_spec.id,fixed.id)
  await wait(async()=>(await api('/generation'+root+'/candidates')).find(item=>item.id===candidate.id)?.status==='succeeded','actual fixed-aspect candidate')
  await command('Page.navigate',{url:link('/ai/candidates',{plan:approved.version_id,shot:'pilot-shot',candidate:candidate.id})})
  await wait(()=>contains('固定制作规格 v2'),'candidate displays its historical, fixed specification')
  await wait(()=>evaluate("document.querySelector('video[aria-label=当前候选]')?.videoWidth===720"),'actual candidate playback metadata')
  const candidateRoot='/generation/candidates/'+candidate.id
  await post(candidateRoot+'/guardian-review',{decision:'approved',note:'本机合成验收'})
  await post(candidateRoot+'/select',{title:'港灯候选',note:'已核对本机合成画面'})
  const assembly='/timeline'+root+'/assemble'
  const timelineInput={series_version_id:approved.version_id,episode:1,profile:'square',title:'港灯时间轴',idempotency_key:'assembly'}
  await blocked(assembly,{...timelineInput,profile:'portrait'},422,'画幅')
  const timeline=await post(assembly,timelineInput)
  assert.equal(timeline.content.production_spec_version_id,fixed.id)
  const director='/director'+root+'/plans'
  const draft=await post(director,{instruction:'使用原批准规格制作第一集',idempotency_key:'director',
    operation:{action:'batch',plan_version_id:approved.version_id,timelines:[{number:1,timeline_version_id:timeline.version_id}],
      policy:{require_audio:false,require_subtitles:false}}})
  assert.equal(draft.production_spec_version_id,fixed.id)
  const started=await post(director+'/'+draft.id+'/execute',{})
  let batch
  await wait(async()=>{
    batch=await api('/production/runs/'+started.run_id)
    return batch.status!=='processing'
  },'actual render and Guardian QC',35000)
  if(batch.status==='needs_review') {
    batch=await post('/production/runs/'+batch.id+'/episodes/1/review',{expected_sha256:batch.episodes[0].qc.output_sha256,
      note:'已预览验收片',idempotency_key:'qc-approval'})
  }
  assert.equal(batch.status,'passed',JSON.stringify(batch))
  assert.equal(batch.production_spec.id,fixed.id)
  assert.equal(batch.episodes[0].qc.production_spec.id,fixed.id)
  await command('Page.navigate',{url:link('/director')})
  await wait(()=>evaluate(`Array.from(document.querySelectorAll('.director-history select option')).some(option=>option.value===${JSON.stringify(draft.id)})`),'fixed plan appears in the director history')
  await setField('项目计划记录',draft.id)
  await wait(()=>contains('固定制作规格 v2'),'director displays the fixed specification')
  await screenshot('production-spec-director.png')

  const agents=root+'/agents/runs'
  const hasOption=(id)=>evaluate(`document.querySelector('.agent-workspace option[value=${JSON.stringify(id)}]')!==null`)
  await wait(()=>hasOption(fixed.id),'Agent fixed spec options')
  await setField('Agent 工作流','preflight')
  await wait(()=>hasOption(approved.version_id),'Agent fixed approved plan')
  await setField('固定制作规格',fixed.id)
  await setField('固定批准计划',approved.version_id)
  await wait(()=>hasOption(timeline.version_id),'Agent timeline for approved plan')
  await setField('固定预检时间轴',timeline.version_id)
  await setField('Agent 制作目标','核对港灯试制的实际镜头和本机时间轴')
  await click('保存 Agent 运行草稿')
  const agentText=text=>evaluate(`document.querySelector('.agent-workspace')?.innerText.includes(${JSON.stringify(text)})`)
  await wait(()=>agentText('待审批'),'preflight pending approval')
  await setField('Agent 审批或审核意见','检查规格 v2 的已批准分镜和时间轴。')
  await click('批准并排队')
  const [preflightDraft]=await api(agents)
  let agentPreflight
  await wait(async()=>{
    agentPreflight=await api(agents+'/'+preflightDraft.id)
    if (agentPreflight.status==='failed') throw new Error(JSON.stringify(agentPreflight.steps))
    return agentPreflight.status==='awaiting_review' && await agentText('待审核')
  },'five preflight Agent roles')
  assert.deepEqual(agentPreflight.steps.map(step=>step.id),['director','art','storyboard','shot_review','postproduction'])
  assert(agentPreflight.steps.every(step=>step.status==='succeeded'))
  assert.equal(agentPreflight.inputs.production_spec.id,fixed.id)
  assert.equal(agentPreflight.inputs.timeline.id,timeline.version_id)
  const preflightResult=agentPreflight.steps.at(-1).result.result
  assert(preflightResult.verified_asset_count>0 && preflightResult.profile==='square')
  await setField('Agent 审批或审核意见','审核通过，已核对本机素材哈希。')
  await click('确认 Agent 输出')
  await wait(()=>agentText('审核通过'),'preflight results reviewed')
  await evaluate("document.querySelector('#director-agent-runs').scrollIntoView({block:'start'})")
  await screenshot('agent-preflight.png')
  await writeFile(join(evidenceDir,'agent-preflight-browser.json'),JSON.stringify({
    roles:agentPreflight.steps.map(step=>step.id),production_spec_version:fixed.version,
    checked_shots:agentPreflight.steps[3].result.result.shot_count,verified_assets:preflightResult.verified_asset_count,
    frame_count:preflightResult.frames,profile:preflightResult.profile,
    output_sha256:agentPreflight.output_sha256,external_cost_cents:agentPreflight.external_cost_cents,
    review:(await api(agents+'/'+preflightDraft.id)).review.decision,
  },null,2)+'\n')

  const packageRoute='/delivery'+root+'/packages'
  const packaging={run_id:batch.id,title:'固定制作规格交付',platform:'local-test',region:'CN',idempotency_key:'delivery'}
  await blocked(packageRoute,{...packaging,region:'US'},422,'交付平台或地域')
  const ready=await api('/delivery'+root+'/runs/'+batch.id+'/readiness?platform=local-test&region=CN')
  assert.equal(ready.production_spec.id,fixed.id)
  for(const asset of ready.blockers) await post('/library/assets/'+asset.asset_id+'/rights',{
    status:'approved',source_type:'owned',holder:'本机样片验收',evidence:'FFmpeg 自制样片，仅验收',
    commercial:true,regions:['CN'],platforms:['local-test'],idempotency_key:'rights'})
  const delivery=await post(packageRoute,packaging)
  let receipt
  await wait(async()=>{
    receipt=await api(packageRoute+'/'+delivery.id)
    if(receipt.status==='failed')throw new Error(receipt.error)
    return receipt.status==='succeeded'
  },'verified delivery archive')
  const response=await fetch(base+'/api/delivery/packages/'+receipt.id+'/file')
  assert.equal(response.status,200)
  const bytes=Buffer.from(await response.arrayBuffer())
  const archive=join(qaRoot,'production-spec.zip')
  await writeFile(archive,bytes)
  assert.equal(createHash('sha256').update(bytes).digest('hex'),receipt.sha256)
  const deliveredSpec=JSON.parse(execFileSync('tar',['-xOf',archive,'production_spec.json'],{timeout:10000}))
  assert.equal(deliveredSpec.id,fixed.id)
  assert.equal(deliveredSpec.sha256,fixed.sha256)
  assert.equal(deliveredSpec.delivery_settings.profile,'square')
  assert(!JSON.stringify(deliveredSpec).includes(note))
  await command('Page.navigate',{url:link('/delivery/library',{run:batch.id})})
  await wait(()=>contains('来自生产批次'),'delivery restores the approved batch')
  await setField('目标平台标识','local-test')
  await setField('目标地域','US')
  await click('检查交付条件')
  await wait(()=>contains('交付平台或地域与固定制作规格不一致'),'delivery presents fixed-region blocker')
  await setField('目标地域','CN')
  await click('检查交付条件')
  await wait(()=>contains('质检与当前授权通过'),'delivery preflight reads the prior spec and actual rights')
  await wait(()=>contains('固定制作规格 v2'),'delivery displays the fixed version')
  await screenshot('production-spec-delivery.png')
  assert.deepEqual(errors,[])
  await writeFile(join(evidenceDir,'production-spec-browser.json'),JSON.stringify({
    tested_at:new Date().toISOString(),versions:[1,fixed.version,newer.version,restored.version],
    pinned_version:fixed.version,stable_contract_sha256:firstHash,independent_app_reload:true,isolated_project:true,
    incomplete_approval_blocked:true,wrong_aspect_and_region_blocked:true,legacy_browser_note_preserved:true,
    approved_run_id:batch.id,render_and_qc_passed:true,verified_zip_bytes:bytes.length,
    simulated_keyframe_fixed_contract:renderedKeyframe.source.contract_sha256,wrong_keyframe_spec_blocked:true,
    delivery_spec:deliveredSpec,external_paid_calls:0,javascript_errors:errors,
  },null,2)+'\n')
  console.log('Production spec Chrome: revision, restore, fresh app read, fixed candidate, director batch, QC and verified delivery passed.')
} catch (error) {
  console.error(await evaluate('document.body.innerText.slice(-4500)'))
  throw error
} finally { await close() }
