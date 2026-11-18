import { spawn, execFileSync } from 'node:child_process'
import { writeFile, readFile } from 'node:fs/promises'
import { join } from 'node:path'
import assert from 'node:assert/strict'

const base = 'http://127.0.0.1:15173'
const qaRoot = process.env.AI_STORY_QA_ROOT
if (!qaRoot) throw new Error('Run through scripts/isolated_regression.py --browser-only')

async function wait(check, label, timeout = 20000) {
  const end = Date.now() + timeout
  while (Date.now() < end) {
    if (await check()) return
    await new Promise(resolve => setTimeout(resolve, 150))
  }
  throw new Error('Timed out: ' + label)
}
async function api(path, options) {
  const response = await fetch(base + '/api' + path, options)
  if (!response.ok) throw new Error(response.status + ' ' + await response.text())
  return response.json()
}
const post = (path, body) => api(path, {
  method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
})
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

const port = 19225
const cdp = 'http://127.0.0.1:' + port
try { await fetch(cdp + '/json/version'); throw new Error('Chrome debug port in use') } catch(error) {
  if (error.message === 'Chrome debug port in use') throw error
}
const browser = spawn('C:/Program Files/Google/Chrome/Application/chrome.exe', [
  '--headless=new','--disable-gpu','--no-first-run', '--window-size=1440,1050',
  '--remote-debugging-port='+port, '--remote-debugging-address=127.0.0.1',
  '--user-data-dir='+join(qaRoot,'chrome'), 'about:blank',
], {windowsHide:true,stdio:'ignore'})
let socket
const pending = new Map(), errors = []
let next = 0
function command(method, params = {}) {
  return new Promise((resolve,reject) => {
    const id = ++next
    pending.set(id, {resolve,reject})
    socket.send(JSON.stringify({id, method, params}))
  })
}
async function evaluate(expression) {
  const data = await command('Runtime.evaluate', {expression, returnByValue:true, awaitPromise:true})
  if (data.exceptionDetails) throw new Error(JSON.stringify(data.exceptionDetails))
  return data.result.value
}
const lit = JSON.stringify
const contains = text => evaluate('document.body.innerText.includes(' + lit(text) + ')')
async function click(text) {
  await wait(() => evaluate(`(() => {
    const button = Array.from(document.querySelectorAll('button')).find(item => item.textContent.trim() === ${lit(text)} && !item.disabled)
    if (!button) return false
    button.click()
    return true
  })()`), 'enabled button: ' + text)
}
async function setField(label, value) {
  assert(await evaluate(`(() => {
    const field = Array.from(document.querySelectorAll('label')).find(item => item.childNodes[0]?.textContent.trim() === ${lit(label)})?.querySelector('input, textarea, select')
    if (!field) return false
    field.value = ${lit(value)}
    field.dispatchEvent(new Event(field.tagName === 'SELECT' ? 'change' : 'input', {bubbles:true}))
    return true
  })()`), label)
}
async function screenshot(filename) {
  const result = await command('Page.captureScreenshot', {format:'png'})
  await writeFile('docs/' + filename, Buffer.from(result.data, 'base64'))
}
try {
  let tab
  await wait(async () => {
    try { tab = (await (await fetch(cdp + '/json')).json()).find(item => item.type === 'page'); return !!tab } catch { return false }
  }, 'Chrome startup')
  socket = new WebSocket(tab.webSocketDebuggerUrl)
  await new Promise((resolve,reject) => { socket.onopen=resolve; socket.onerror=reject })
  socket.onmessage = ({data}) => {
    const message = JSON.parse(data)
    const call = pending.get(message.id)
    if (call) {
      pending.delete(message.id)
      if (message.error) call.reject(new Error(JSON.stringify(message.error)))
      else call.resolve(message.result)
    } else if (message.method === 'Runtime.exceptionThrown') {
      errors.push(message.params.exceptionDetails)
    }
  }
  await command('Runtime.enable')
  await command('Page.enable')
  await command('Page.navigate',{url:base})
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
  await setField('持续秒数', '1').catch(async () => {
    await evaluate("const input=document.querySelectorAll('input[type=number]')[2];input.value='1';input.dispatchEvent(new Event('input',{bubbles:true}))")
  })
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
  await writeFile('docs/p5-browser-acceptance.json',JSON.stringify({
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
  if (socket?.readyState === WebSocket.OPEN) await command('Browser.close').catch(() => {})
  socket?.close()
  await new Promise(resolve => {
    if (browser.exitCode !== null) return resolve()
    browser.once('exit', resolve)
    setTimeout(() => { browser.kill(); resolve() }, 3000).unref()
  })
}
