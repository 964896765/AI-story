import { spawn } from 'node:child_process'
import { writeFile } from 'node:fs/promises'
import { join } from 'node:path'
import assert from 'node:assert/strict'

export const qaRoot = process.env.AI_STORY_QA_ROOT
export const base = 'http://127.0.0.1:' + process.env.AI_STORY_QA_WEB_PORT
export const evidenceDir = process.env.AI_STORY_QA_EVIDENCE || qaRoot

export async function wait(check, label, timeout = 20000) {
  const end = Date.now() + timeout
  while (Date.now() < end) {
    if (await check()) return
    await new Promise(resolve => setTimeout(resolve, 150))
  }
  throw new Error('Timed out: ' + label)
}
export async function api(path, options) {
  const response = await fetch(base + '/api' + path, options)
  if (!response.ok) throw new Error(response.status + ' ' + await response.text())
  return response.json()
}
export const post = (path, body) => api(path, {
  method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
})

const workspaceTargets = {
  '项目总览':['项目总览'], '素材资产中心':['项目与素材','assets'], '智能解析':['项目与素材','analysis'],
  '漫剧定制':['剧本与创作','story'], '剧情改编':['剧本与创作','adaptation'], '角色与场景':['角色与场景'],
  '分镜编辑':['分镜工作台','storyboard'], '故事圣经':['分镜工作台','bible'],
  '生成候选':['AI 创作中心'], '配音与字幕':['配音与声音'], '多轨时间轴':['剪辑与时间轴','timeline'],
  '智能二创':['剪辑与时间轴','video'], '批量生产':['批量生产'], '质检与导出':['质检与交付','quality'],
  '资源与交付':['质检与交付','library'], '运营中心':['发行与运营'], '运行诊断':['模型与系统设置','system'],
  '文本模型与预算':['模型与系统设置','models'],
}

export async function navigateWorkspace(evaluate, text) {
  const target = workspaceTargets[text]
  if (!target || !await evaluate("document.querySelector('nav a[data-workspace]')!==null")) return false
  const [group,page] = target
  const selector = JSON.stringify(`nav a[data-workspace="${group}"]`)
  await wait(() => evaluate(`(() => {
    const link=document.querySelector(${selector})
    if (!link) return false
    if (!link.classList.contains('nav-active')) link.click()
    return true
  })()`), 'workspace group: ' + group)
  if (page) {
    await wait(() => evaluate(`(() => {
      const tab=document.querySelector('[data-page="${page}"]')
      if (!tab) return false
      if (tab.getAttribute('aria-current') !== 'page') tab.click()
      return true
    })()`), 'workspace page: ' + page)
    await wait(() => evaluate(`document.querySelector('[data-page="${page}"]')?.getAttribute('aria-current') === 'page'`), 'route applied: ' + page)
  }
  return true
}

export async function openChrome(port) {
  if (!qaRoot) throw new Error('Run through scripts/isolated_regression.py --browser-only')
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
    if (await navigateWorkspace(evaluate,text)) return
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
    await writeFile(join(evidenceDir, filename), Buffer.from(result.data, 'base64'))
  }
  async function close() {
    if (socket?.readyState === WebSocket.OPEN) await command('Browser.close').catch(() => {})
    socket?.close()
    await new Promise(resolve => {
      if (browser.exitCode !== null) return resolve()
      browser.once('exit', resolve)
      setTimeout(() => { browser.kill(); resolve() }, 3000).unref()
    })
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
    return { command, evaluate, contains, click, setField, screenshot, errors, close }
  } catch (error) {
    await close()
    throw error
  }
}
