import { execFileSync } from 'node:child_process'
import { writeFile, readFile } from 'node:fs/promises'
import { join } from 'node:path'
import assert from 'node:assert/strict'
import { api, base, evidenceDir, openChrome, post, qaRoot, wait } from './chrome-qa.mjs'

await wait(async () => {
  try { return (await api('/health')).ready && (await api('/queue')).workers.some(worker => worker.online) } catch { return false }
}, 'isolated API, Vite proxy and worker')
assert.equal((await api('/text/status')).live_authorized, false)
const project = await post('/projects', { name: 'P5 浏览器自编样本' })
const projectPath = '/projects/' + project.id
const source = await post(projectPath + '/story/entities', {
  kind: 'novel', title: '港口来信', content: { text: '黎明时，阿青在港口找到一封旧信。', authorization: '自编验收故事' },
  idempotency_key: 'p5-novel',
})
const fixture = join(qaRoot, 'owned.mp4')
execFileSync('ffmpeg', ['-v','error','-f','lavfi','-i','testsrc2=size=320x240:rate=24','-t','2','-c:v','mpeg4',fixture], {timeout: 15000})
const upload = new FormData()
upload.set('file', new Blob([await readFile(fixture)], {type:'video/mp4'}), 'owned.mp4')
upload.set('authorization', '自行生成的色彩图案，用于本机验收')
await api(projectPath + '/assets', { method:'POST', body:upload })

const {command, evaluate, contains, click, setField, screenshot, errors, close} = await openChrome(19225)
try {
  await wait(() => contains('服务就绪'), 'workbench ready')
  await setField('当前项目', project.id)
  await click('漫剧定制')
  await wait(() => contains('港口来信'), 'source loaded')
  await evaluate("Array.from(document.querySelectorAll('.story-item')).find(b => b.textContent.includes('港口来信')).click()")
  await wait(() => contains('使用此版本改编剧情'), 'source version is ready')
  await click('使用此版本改编剧情')
  await wait(() => contains('真实调用已关闭'), 'model controls loaded')
  await setField('模拟配置名称','P5 浏览器模拟')
  await click('添加离线模拟配置')
  await wait(() => evaluate("Array.from(document.querySelectorAll('option')).some(option => option.textContent.includes('P5 浏览器模拟'))"), 'provider persisted')
  await setField('项目模拟额度（元）','1')
  await click('保存模拟额度')
  await wait(() => contains('核算或已付'), 'budget persisted')
  await setField('改编目标','把港口发现改成悬疑开场')
  await click('查看预留上限')
  await wait(() => contains('模拟预留上限'), 'budget quote')
  await click('提交改编')
  await wait(() => contains('待审核草稿 v1'), 'worker generated offline fixture')
  const firstCall = (await api('/text' + projectPath + '/calls'))[0]
  await click('提交改编')
  await wait(() => contains('待审核草稿 v1'), 'duplicate submission returns the existing draft')
  assert.equal((await api('/text' + projectPath + '/calls')).length, 1)
  await click('对比已保存草稿与原稿')
  await wait(() => contains('待审核改编稿'), 'original-to-draft diff')
  const revised = '阿青提起一盏灯，沿着线索寻找寄信人。'
  await setField('改编正文', revised)
  await click('保存草稿修订')
  await wait(() => contains('待审核草稿 v2'), 'draft revision persisted')
  await setField('审核意见','人工审阅完成，允许用于本地样本剪辑。')
  await evaluate("Array.from(document.querySelectorAll('button')).find(b => b.textContent.trim() === '批准并保存为新剧本').scrollIntoView({block:'center'})")
  await screenshot('p5-review.png')
  assert(await evaluate(`Array.from(document.querySelectorAll('button')).find(b => b.textContent.trim() === '批准并保存为新剧本').focus(); document.activeElement.textContent.trim() === '批准并保存为新剧本'`))
  await command('Input.dispatchKeyEvent',{type:'keyDown',key:'Enter',code:'Enter',text:'\r',windowsVirtualKeyCode:13})
  await command('Input.dispatchKeyEvent',{type:'keyUp',key:'Enter',code:'Enter',windowsVirtualKeyCode:13})
  await wait(() => contains('引用已审核剧本创建剪辑批次'), 'keyboard review accepted')
  const [call] = await api('/text' + projectPath + '/calls')
  const version = await api('/story/versions/' + call.accepted_version_id)
  assert.equal(version.content.body, revised)
  assert.equal(version.provenance.simulated, true)
  assert.equal((await api('/story/versions/' + source.version_id)).content.text, source.content.text)
  await click('引用已审核剧本创建剪辑批次')
  await wait(() => contains('生产依据'), 'editor has accepted version')
  await evaluate("document.querySelector('input[type=checkbox]').click()")
  await setField('裁剪时长（可空）', '1')
  await evaluate("document.querySelector('form').requestSubmit()")
  await wait(() => contains('已确认 1 项任务入队'), 'render task submitted')
  let render
  await wait(async () => {
    render = (await api(projectPath + '/tasks')).find(task => task.kind === 'render')
    if (render?.status === 'failed') throw new Error(render.error)
    return render?.status === 'succeeded'
  }, 'real video completed')
  assert.equal(render.story_version_id, call.accepted_version_id)
  const checked = JSON.parse(execFileSync('ffprobe', ['-v','error','-show_format','-show_streams','-of','json',join(qaRoot,render.output.storage_key)], {encoding:'utf8',timeout:15000}))
  assert(checked.streams.some(stream => stream.codec_type === 'video'))
  assert(Number(checked.format.duration) >= 0.9 && Number(checked.format.duration) <= 1.1)
  const response = await fetch(base + '/api/tasks/' + render.id + '/output', {headers:{Range:'bytes=0-99'}})
  assert.equal(response.status, 206)
  assert.equal((await response.arrayBuffer()).byteLength, 100)
  assert.equal(call.actual_cost_micros, null)
  assert.deepEqual(errors,[])
  await writeFile(join(evidenceDir,'p5-browser-acceptance.json'),JSON.stringify({
    browser:'Installed Chrome headless', project_id:project.id, source_version_id:source.version_id,
    checked_at:new Date().toISOString(), real_external_model_requests:0, real_spent_micros:0,
    duplicate_submission_same_call:firstCall.id === call.id, ffprobe_verified:true,
    draft_revision:call.draft_revision, simulated:call.simulated, compiled_version:call.accepted_version_id,
    keyboard_review:true, render_task:render.id, status:render.status, range:response.status,
    render_duration:render.output.duration, render_sha256:render.output.sha256, actual_cost_micros:call.actual_cost_micros,
    javascript_errors:errors,
  },null,2)+'\n')
  console.log('P5 browser: version pin, simulated creation, edit, keyboard approval and verified real local media passed.')
} catch (error) {
  console.error(await evaluate('document.body.innerText.slice(-8000)'))
  throw error
} finally {
  await close()
}
