import assert from 'node:assert/strict'
import { writeFile } from 'node:fs/promises'
import { join } from 'node:path'
import { api, base, evidenceDir, openChrome, post, wait } from './chrome-qa.mjs'

await wait(async()=>{
  try {return (await api('/health')).ready&&(await api('/queue')).workers.some(node=>node.online)} catch{return false}
},'isolated app')
const configured=await api('/voice/capabilities')
const locales=['zh-CN','en-US']
const voices=locales.map(locale=>configured.voices.find(voice=>voice.locale===locale))
assert(voices.every(Boolean),'Installed offline Mandarin and English voices are required')
assert.equal(configured.network_enabled,false)
const project=await post('/projects',{name:'P9 双角色自编配音验收'})
const path='/projects/'+project.id
const create=(kind,title,content,idempotency_key)=>post(path+'/story/entities',{kind,title,content,idempotency_key})
const script=await create('script','晚安港口',{body:'阿青：晚安。\n守塔人：Good night.'},'script')
const characters=await Promise.all([
  create('character','阿青',{},'first'),create('character','守塔人',{},'second'),
])
const board=await create('storyboard','两句对白',{
  source_version_id:script.version_id,
  shots:characters.map((role,i)=>({number:i+1,description:'角色说话',shot_id:'night-'+(i+1),
    planned_duration:5,dialogue:['晚安，海港。','Good night.'][i],
    character_version_ids:[role.version_id],speaker_version_id:role.version_id})),
},'board')
const {command,evaluate,contains,click,setField,screenshot,errors,close}=await openChrome(19229)
try{
  await wait(()=>contains('服务就绪'),'app ready')
  await setField('当前项目',project.id)
  await click('配音与字幕')
  await wait(()=>evaluate(`document.querySelector('option[value="${board.version_id}"]')!==null`),'board listed')
  await setField('固定分镜',board.version_id)
  await wait(()=>evaluate("document.querySelectorAll('.voice-workbench form fieldset').length===2"),'two speakers loaded')
  const consent='本机验收使用自编短句和已安装的离线系统音色。'
  await evaluate(`document.querySelectorAll('.voice-workbench form fieldset').forEach((section,i)=>{
    const voice=section.querySelector('select')
    voice.value=${JSON.stringify(voices.map(item=>item.name))}[i]
    voice.dispatchEvent(new Event('change',{bubbles:true}))
    const note=section.querySelector('textarea')
    note.value=${JSON.stringify(consent)}
    note.dispatchEvent(new Event('input',{bubbles:true}))
  })`)
  await click('生成配音和字幕')
  await wait(()=>contains('配音任务已排队'),'voice jobs queued')
  await wait(()=>evaluate("document.querySelector('.voice-workbench audio')?.readyState>=1"),'native speech heard by browser media decoder')
  await setField('素材名称','晚安港口配音')
  await setField('采纳说明','已试听两种音色并核对字幕时间。')
  await screenshot('p9-voice-review.png')
  await evaluate("Array.from(document.querySelectorAll('button')).find(b=>b.textContent.trim()==='采纳音轨和字幕').focus()")
  await command('Input.dispatchKeyEvent',{type:'keyDown',key:'Enter',code:'Enter',text:'\r',windowsVirtualKeyCode:13})
  await command('Input.dispatchKeyEvent',{type:'keyUp',key:'Enter',code:'Enter',windowsVirtualKeyCode:13})
  await wait(()=>contains('已采纳音轨和 SRT 字幕'),'keyboard adoption')
  const [job]=await api('/voice'+path+'/tasks')
  assert.equal(job.status,'succeeded')
  assert.deepEqual(job.output.cues.map(line=>line.start_ms),[0,5000])
  const wav=await fetch(base+'/api/voice/tasks/'+job.id+'/files/dialogue.wav',{headers:{Range:'bytes=0-99'}})
  assert.equal(wav.status,206)
  assert.equal(Buffer.from(await wav.arrayBuffer()).subarray(0,4).toString(),'RIFF')
  const assets=await api(path+'/assets')
  assert.deepEqual(assets.map(item=>item.name).sort(),['晚安港口配音.srt','晚安港口配音.wav'])
  assert.deepEqual(errors,[])
  await writeFile(join(evidenceDir,'p9-browser-acceptance.json'),JSON.stringify({
    checked_at:new Date().toISOString(),browser:'Installed Chrome headless',native_voice_locales:locales,
    verified_task:job.id,storyboard_version_id:board.version_id,cues:job.output.cues.map(c=>[c.start_ms,c.end_ms]),
    wav_range_status:wav.status,adopted_assets:assets.map(item=>item.name),keyboard_adoption:true,
    external_cost_micros:job.output.actual_external_cost_micros,javascript_errors:errors,
  },null,2)+'\n')
  console.log('P9 browser: two real offline voices, sample-aligned subtitles, WAV preview and adoption passed.')
} catch(error){
  console.error(await evaluate('document.body.innerText.slice(-6500)'))
  throw error
} finally{await close()}
