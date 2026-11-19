import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { readFile, writeFile } from 'node:fs/promises'
import { join } from 'node:path'
import { api, base, evidenceDir, openChrome, post, qaRoot, wait } from './chrome-qa.mjs'

await wait(async()=>{
  try{return (await api('/health')).ready&&(await api('/queue')).workers.some(worker=>worker.online)}catch{return false}
},'isolated app')
const project=await post('/projects',{name:'P10 多轨实际合成浏览器样本'})
const path='/projects/'+project.id
const video=join(qaRoot,'owned-bars.mp4'),audio=join(qaRoot,'owned-tone.wav')
execFileSync('ffmpeg',['-v','error','-f','lavfi','-i','testsrc2=size=320x240:rate=24:duration=2',
  '-c:v','libx264','-pix_fmt','yuv420p','-threads','1',video],{timeout:20000})
execFileSync('ffmpeg',['-v','error','-f','lavfi','-i','sine=frequency=500:sample_rate=48000:duration=2',
  '-c:a','pcm_s16le',audio],{timeout:20000})
async function add(name,content){
  const body=new FormData()
  body.set('file',new Blob([content]),name)
  body.set('authorization','本机自行生成测试素材')
  return api(path+'/assets',{method:'POST',body})
}
const [clip,wave,captions]=await Promise.all([
  add('owned-bars.mp4',await readFile(video)),add('owned-tone.wav',await readFile(audio)),
  add('owned-captions.srt','1\n00:00:00,250 --> 00:00:01,500\nOwned local sample\n'),
])
const {evaluate,contains,click,setField,screenshot,errors,close}=await openChrome(19230)
async function addClip(index,id){
  await evaluate(`document.querySelectorAll('.lane')[${index}].querySelectorAll('.lane-controls button')[2].click()`)
  await wait(()=>evaluate(`document.querySelector('.timeline-session select option[value="${id}"]')!==null`),'asset option')
  await setField('片段素材',id)
}
try{
  await wait(()=>contains('服务就绪'),'app ready')
  await setField('当前项目',project.id)
  await click('多轨时间轴')
  await wait(()=>contains('保存时间轴版本'),'editor visible')
  await setField('时间轴标题','本机真实多轨剪辑')
  await setField('输出画幅','square')
  await setField('总帧数（24 fps）','48')
  await addClip(0,clip.id)
  await setField('附加轨道','dialogue')
  await click('添加轨道')
  await addClip(1,wave.id)
  await setField('附加轨道','caption')
  await click('添加轨道')
  await addClip(2,captions.id)
  await click('保存时间轴版本')
  await wait(()=>contains('时间轴 v1 已保存'),'version committed')
  await click('渲染已保存版本')
  await wait(()=>contains('已提交固定版本多轨渲染'),'render queued')
  await click('预览多轨成片')
  await wait(()=>evaluate("document.querySelector('.timeline-workbench video')?.readyState>=1"),'Chrome decoded verified MP4')
  const [render]=await api('/timeline'+path+'/renders')
  assert.equal(render.output.frames,48)
  assert.equal(render.output.has_audio,true)
  const firstVersion=render.story_version_id
  const returned=await fetch(base+'/api/tasks/'+render.id+'/output',{headers:{Range:'bytes=0-255'}})
  assert.equal(returned.status,206)
  await screenshot('p10-multitrack.png')

  await click('owned-captions.srt')
  await setField('时长（帧）','40')
  await setField('时间轴位置（帧）','4')
  await click('保存时间轴版本')
  await wait(()=>contains('时间轴 v2 已保存'),'clip moved and saved')
  await evaluate("Array.from(document.querySelectorAll('summary')).find(s=>s.textContent.trim()==='历史版本').click()")
  await click('v1')
  await click('追加恢复此版')
  await wait(()=>contains('已追加恢复时间轴 v3'),'append-only restored timeline')
  const [restored]=(await api(path+'/story/entities?kind=timeline')).items
  const recovered=await api('/timeline/versions/'+restored.version_id+'/manifest')
  const original=await api('/timeline/versions/'+firstVersion+'/manifest')
  assert.deepEqual(recovered.timeline,original.timeline)
  assert.deepEqual(errors,[])
  await writeFile(join(evidenceDir,'p10-browser-acceptance.json'),JSON.stringify({
    checked_at:new Date().toISOString(),browser:'Installed Chrome headless',real_render_task:render.id,
    source_version_id:firstVersion,restored_version_id:restored.version_id,restored_version:restored.version,
    output_sha256:render.output.sha256,output_frames:render.output.frames,real_browser_preview:true,range_status:returned.status,
    tracks:recovered.timeline.tracks.map(track=>track.role),javascript_errors:errors,
  },null,2)+'\n')
  console.log('P10: browser timeline edit, valid multitrack MP4, Range and version restore passed.')
} catch(error){
  console.error(await evaluate('document.body.innerText.slice(-7000)'))
  throw error
} finally{await close()}
