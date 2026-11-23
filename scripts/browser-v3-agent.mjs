import assert from 'node:assert/strict'
import { writeFile } from 'node:fs/promises'
import { join } from 'node:path'
import { api, base, evidenceDir, openChrome, post, wait } from './chrome-qa.mjs'

await wait(async()=>{
  try { return (await api('/health')).ready && (await api('/queue')).workers.some(worker=>worker.online) }
  catch { return false }
},'isolated Agent services')
const project=await post('/projects',{name:'Agent 验收 · 港灯'})
const root='/projects/'+project.id
const spec=await post(root+'/production-specs',{expected_version:0,idempotency_key:'fixed-spec',settings:{
  episode_count:2,episode_duration_ms:1500,style:'平面线稿',profile:'square',width:720,height:720,
  fps:24,platform:'local-test',region:'CN',budget_cents:0,
}})
const novel=await post(root+'/story/entities',{kind:'novel',title:'港灯原稿',idempotency_key:'novel',content:{
  text:'守灯人点亮港灯，雾中的船终于看清岸线。\n\n返航的船长把遗失的怀表送回灯塔。',authorization:'本测试自编原创',
}})
const endpoint=root+'/agents/runs'
const {command,evaluate,contains,click,setField,screenshot,errors,close}=await openChrome(19246)
try {
  await command('Page.navigate',{url:base+'/director?project='+project.id+'#director-agent-runs'})
  await wait(()=>evaluate(`document.querySelector('.agent-workspace option[value=${JSON.stringify(novel.version_id)}]')!==null`),'fixed Agent source')
  await wait(()=>evaluate(`document.querySelector('.agent-workspace option[value=${JSON.stringify(spec.id)}]')!==null`),'fixed Agent spec')
  await setField('固定制作规格',spec.id)
  await setField('固定原稿',novel.version_id)
  await setField('Agent 制作目标','为原创短篇准备两集试制草案')
  await click('保存 Agent 运行草稿')
  const panelText=text=>evaluate(`document.querySelector('.agent-workspace')?.innerText.includes(${JSON.stringify(text)})`)
  await wait(()=>panelText('待审批'),'Agent draft appears')
  const [draft]=await api(endpoint)
  assert.equal(draft.status,'awaiting_approval')
  assert.deepEqual(await api(root+'/tasks'),[])
  await setField('Agent 审批或审核意见','确认仅执行本机规则，使用固定原稿及规格。')
  await click('批准并排队')
  await wait(()=>panelText('待审核'),'completed local Agent steps')
  const output=await api(endpoint+'/'+draft.id)
  assert.equal(output.status,'awaiting_review')
  assert.equal(output.inputs.source.id,novel.version_id)
  assert.equal(output.inputs.production_spec.id,spec.id)
  assert.equal(output.external_cost_cents,0)
  assert.deepEqual(output.steps.map(step=>[step.id,step.status]),[['director','succeeded'],['analysis','succeeded'],['writer','succeeded']])
  assert(output.steps[2].result.result.requires_human_edit)
  assert.equal(output.steps[2].result.previous_result_sha256,output.steps[1].result.result_sha256)
  await evaluate(`Array.from(document.querySelectorAll('.agent-steps summary')).find(item=>item.innerText==='查看 编剧 结果').click()`)
  await setField('Agent 审批或审核意见','核对了本机原稿摘录，草案需经人工创作。')
  await click('确认 Agent 输出')
  await wait(()=>panelText('审核通过'),'human review recorded')
  await command('Page.reload')
  await wait(()=>panelText('审核通过'),'review persisted after browser reload')
  const reviewed=await api(endpoint+'/'+draft.id)
  assert.equal(reviewed.review.output_sha256,output.output_sha256)
  assert.deepEqual(errors,[])
  await evaluate("document.querySelector('#director-agent-runs').scrollIntoView({block:'start'})")
  await screenshot('agent-story.png')
  await writeFile(join(evidenceDir,'agent-story-browser.json'),JSON.stringify({
    steps:reviewed.steps.map(step=>({role:step.id,status:step.status,attempt:step.attempt,sha256:step.result.result_sha256})),
    tasks_before_approval:0,browser_reload_preserved_review:true,review:reviewed.review.decision,
    input_sha256:reviewed.input_sha256,output_sha256:reviewed.output_sha256,
    external_cost_cents:reviewed.external_cost_cents,javascript_errors:errors,
  },null,2)+'\n')
  console.log('Agent Chrome: fixed input, human approval, Worker handoffs, output review and reload passed.')
} catch (error) {
  console.error((await evaluate("document.querySelector('#director-agent-runs')?.innerText")) || await evaluate('document.body.innerText.slice(-3500)'))
  throw error
} finally { await close() }
