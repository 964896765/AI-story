import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { readFile, writeFile } from 'node:fs/promises'
import { join } from 'node:path'
import { api, base, evidenceDir, post, qaRoot, wait } from './chrome-qa.mjs'

await wait(async()=>{
  try { return (await api('/health')).ready && (await api('/queue')).workers.some(node=>node.online) }
  catch { return false }
},'isolated production services')
const project = await post('/projects',{name:'V3 制作负载验收'})
const root = '/projects/'+project.id
const movie = join(qaRoot,'production-load.mp4')
const seconds=30, episodeCount=6
execFileSync('ffmpeg',['-v','error',
  '-f','lavfi','-i',`testsrc2=size=640x360:rate=24:duration=${seconds}`,
  '-f','lavfi','-i',`sine=frequency=450:sample_rate=48000:duration=${seconds}`,
  '-c:v','libx264','-threads','2','-preset','ultrafast','-c:a','aac',movie],{timeout:40000})
async function upload(bytes,name) {
  const form=new FormData()
  form.set('file',new Blob([bytes]),name)
  form.set('authorization','本机自产的测试画面、音调和字幕')
  return api(root+'/assets',{method:'POST',body:form})
}
const [source,subtitle] = await Promise.all([
  readFile(movie).then(bytes=>upload(bytes,'制作负载样片.mp4')),
  upload('1\n00:00:01,000 --> 00:00:03,000\n海港制作验收\n\n2\n00:00:27,000 --> 00:00:29,000\n固定源时间\n','制作负载字幕.srt'),
])
const story=(kind,title,content,key)=>post(root+'/story/entities',{kind,title,content,idempotency_key:key})
const script=await story('script','海港负载样本',{body:'用自制素材验证本地制作和交付流程。'},'script')
const episodes=[]
for (let number=1; number<=episodeCount; number++) {
  const episode=await story('episode','第 '+number+' 集',{number,body:'海港出现光线。',source_version_id:script.version_id},'ep-'+number)
  const storyboard=await story('storyboard','分镜 '+number,{source_version_id:episode.version_id,
    shots:[{number:1,description:'海港定镜',planned_duration:seconds}]},'board-'+number)
  episodes.push({episode_version_id:episode.version_id,storyboard_version_id:storyboard.version_id,target_duration_ms:seconds*1000})
}
const bible=await story('story_bible','海港制作计划',{script_version_id:script.version_id,theme:'海港',world:'自编港口',episodes},'bible')
const plan=await post('/series/entities/'+bible.id+'/approve',{expected_version:1,note:'批准自有负载样本',idempotency_key:'approved'})
const timelines=[]
const frames=seconds*24
for (let number=1; number<=episodeCount; number++) {
  const clip=(id,asset)=>({id,asset_id:asset.id,at:0,frames})
  const timeline=await story('timeline','制作时间轴 '+number,{source_version_id:plan.version_id,frames,profile:'landscape',tracks:[
    {id:'main',role:'main',clips:[clip('video',source)]},
    {id:'audio',role:'dialogue',clips:[clip('sound',source)]},
    {id:'captions',role:'caption',clips:[clip('subtitle',subtitle)]},
  ]},'timeline-'+number)
  timelines.push({number,timeline_version_id:timeline.version_id})
}

const path='/production'+root+'/runs'
async function production(body, label) {
  const started=performance.now()
  let run=await post(path,body)
  await wait(async()=>{
    run=await api(path+'/'+run.id)
    if (['needs_rework','needs_review','cancelled'].includes(run.status)) throw new Error(JSON.stringify(run.episodes))
    return run.status==='passed'
  },label,160000)
  return {run,seconds:Math.round(performance.now()-started)/1000}
}
const policy={require_audio:true,require_subtitles:true}
const original=await production({plan_version_id:plan.version_id,timelines,policy,idempotency_key:'load-original'},'six real renders and technical QC')
assert.equal(original.run.passed,episodeCount)
const updated=await production({plan_version_id:plan.version_id,previous_run_id:original.run.id,timelines:[],
  policy,recheck_quality:true,idempotency_key:'load-recheck'},'six reports recomputed from the same videos')
assert.equal(updated.run.rechecked,episodeCount)
for (let i=0; i<episodeCount; i++) {
  const first=original.run.episodes[i], current=updated.run.episodes[i]
  assert.equal(current.render_task_id,first.render_task_id)
  assert.notEqual(current.qc_task_id,first.qc_task_id)
  assert.equal(current.qc.output_sha256,first.qc.output_sha256)
  assert.equal(current.qc.captions.cue_count,2)
  assert.equal(current.qc.audio.status,'measured')
}
const tasks=await api(root+'/tasks?limit=40')
const renders=tasks.filter(task=>task.kind==='timeline_render')
const checks=tasks.filter(task=>task.kind==='qc_review')
assert.equal(renders.length,episodeCount)
assert.equal(checks.length,episodeCount*2)
assert(renders.every(task=>task.output.width===1280 && task.output.height===720 && task.output.frames===frames))
const sample=renders[0]
const response=await fetch(base+'/api/tasks/'+sample.id+'/output')
assert.equal(response.status,200)
assert.equal(createHash('sha256').update(Buffer.from(await response.arrayBuffer())).digest('hex'),sample.output.sha256)
const system=await api('/system/metrics')
const queue=await api('/queue')
assert.equal(queue.workers.filter(node=>node.online).length,1)
const sum=(items,key)=>items.reduce((total,item)=>total+key(item),0)
await writeFile(join(evidenceDir,'v3-production-load-acceptance.json'),JSON.stringify({
  checked_at:new Date().toISOString(),resolution:[1280,720],fps:24,episode_count:episodeCount,
  seconds_per_episode:seconds,generated_video_seconds:seconds*episodeCount,worker_count:1,logical_cpus:system.logical_cpus,
  full_batch_wall_seconds:original.seconds,recheck_only_wall_seconds:updated.seconds,total_render_task_seconds:sum(renders,t=>t.elapsed_seconds),
  renders:renders.length,qc_tasks:checks.length,rechecked_without_rerender:updated.run.rechecked,
  output_bytes:sum(renders,t=>t.output.size_bytes),verified_download_sha256:sample.output.sha256,external_paid_calls:0,
},null,2)+'\n')
console.log(`V3 production load: ${episodeCount} x ${seconds}s delivered 720p renders and QC in ${original.seconds}s, rechecked in ${updated.seconds}s.`)
