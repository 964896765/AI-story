import { spawn } from 'node:child_process'
import { writeFile } from 'node:fs/promises'
import { join } from 'node:path'
import assert from 'node:assert/strict'

export const qaRoot = process.env.AI_STORY_QA_ROOT
if (!qaRoot) throw new Error('Run through scripts/isolated_regression.py --browser-only')
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

export async function openChrome(port) {
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
