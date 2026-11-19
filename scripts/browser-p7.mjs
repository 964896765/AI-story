import assert from 'node:assert/strict'
import { writeFile } from 'node:fs/promises'
import { join } from 'node:path'
import { api, evidenceDir, openChrome, post, wait } from './chrome-qa.mjs'

await wait(async () => {
  try { return (await api('/health')).ready } catch { return false }
}, 'isolated app')
const project=await post('/projects',{name:'P7 三集自编验收'})
const entities='/projects/'+project.id+'/story/entities'
const create=(kind,title,content,idempotency_key)=>post(entities,{kind,title,content,idempotency_key})
const source=await create('script','纸灯约定',{body:'阿青寻找港口的守灯人。'},'main')
const actor=await create('character','阿青',{appearance:'灰围巾与绿风衣'},'actor')
const scene=await create('scene','旧码头',{location:'海湾东侧'},'dock')
const episodes=[]
for(const [i,body] of ['在雨中捡到信','赶到海湾东岸','归还旧信'].entries()){
  const episode=await create('episode','第 '+(i+1)+' 集',{number:i+1,body,source_version_id:source.version_id},'episode-'+i)
  const storyboard=await create('storyboard','分镜 '+(i+1),{
    source_version_id:episode.version_id,shots:[{number:1,shot_id:'paper-lamp-'+(i+1),description:body,
      planned_duration:3,character_version_ids:[actor.version_id],scene_version_id:scene.version_id,framing:'medium'}]
  },'board-'+i)
  episodes.push({episode,storyboard})
}
const {command, evaluate, contains, click, setField, screenshot, errors, close}=await openChrome(19227)
try{
  await wait(()=>contains('服务就绪'),'app ready')
  await setField('当前项目',project.id)
  await click('故事圣经')
  const sourceOption=`document.querySelector('.series-form option[value="${source.version_id}"]')!==null`
  await wait(()=>evaluate(sourceOption),'fixed versions visible')
  await setField('故事圣经标题','纸灯三集计划')
  await setField('固定总剧本',source.version_id)
  await setField('主题','按时归还失物')
  await setField('世界观','临海港口靠灯塔夜间引航')
  for(const {episode,storyboard} of episodes){
    await click('添加分集计划')
    await evaluate(`(() => {
      const group=[...document.querySelectorAll('.series-form > fieldset')].at(-1)
      const [episode,board]=group.querySelectorAll('select')
      episode.value=${JSON.stringify(episode.version_id)}
      episode.dispatchEvent(new Event('change',{bubbles:true}))
      board.value=${JSON.stringify(storyboard.version_id)}
      board.dispatchEvent(new Event('change',{bubbles:true}))
    })()`)
  }
  assert.deepEqual(await evaluate("Array.from(document.querySelectorAll('form .series-form :invalid,.series-form :invalid')).map(field=>field.closest('label')?.textContent.trim())"),[])
  await click('保存并校验')
  await wait(()=>contains('规则检查已完成，可以人工审核'),'three episodes validated')
  await setField('审核说明','按自编三集、固定角色与场景审阅通过。')
  await evaluate("Array.from(document.querySelectorAll('button')).find(b=>b.textContent.trim()==='批准固定制作计划').focus()")
  await screenshot('p7-series-review.png')
  await command('Input.dispatchKeyEvent',{type:'keyDown',key:'Enter',code:'Enter',text:'\r',windowsVirtualKeyCode:13})
  await command('Input.dispatchKeyEvent',{type:'keyUp',key:'Enter',code:'Enter',windowsVirtualKeyCode:13})
  await wait(()=>contains('固定版本已批准'),'keyboard approval persisted')
  const [version]=(await api(entities+'?kind=story_bible')).items
  const report=await api('/series/versions/'+version.version_id+'/continuity')
  assert.equal(report.approved,true)
  assert.equal(report.episodes.length,3)
  assert(report.episodes.every(episode=>episode.planned_duration_ms===3000))
  assert.deepEqual(report.episodes.map(episode=>episode.shots[0].shot_id),['paper-lamp-1','paper-lamp-2','paper-lamp-3'])
  assert.deepEqual(errors,[])
  await writeFile(join(evidenceDir,'p7-browser-acceptance.json'),JSON.stringify({
    checked_at:new Date().toISOString(),browser:'Installed Chrome headless',approved_version_id:version.version_id,
    episode_count:report.episodes.length,stable_shot_ids:report.episodes.map(episode=>episode.shots[0].shot_id),
    test_plan_durations_ms:report.episodes.map(episode=>episode.planned_duration_ms),keyboard_approval:true,
    real_external_calls:0,javascript_errors:errors,
  },null,2)+'\n')
  console.log('P7 browser: three episodes, fixed storyboard and keyboard approval verified.')
} catch(error) {
  console.error(await evaluate('document.body.innerText.slice(-6000)'))
  throw error
} finally {
  await close()
}
