// Uses installed Chrome and Node 20 --experimental-websocket. No browser download.
import { spawn } from 'node:child_process'
import { readFile, mkdir, writeFile } from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..')
const port=19222
try{await fetch(`http://127.0.0.1:${port}/json/version`);throw new Error('QA debugging port already occupied')}catch(e){if(e.message==='QA debugging port already occupied')throw e}
const browser=spawn('C:/Program Files/Google/Chrome/Application/chrome.exe',['--headless=new','--disable-gpu',`--remote-debugging-port=${port}`,'--remote-debugging-address=127.0.0.1',`--user-data-dir=${path.join(root,'data/browser-p2')}`,'--no-first-run','--window-size=1440,1100','about:blank'],{windowsHide:true,stdio:'ignore'})
let socket
const delay=ms=>new Promise(r=>setTimeout(r,ms))
async function wait(fn,description,timeout=30000){const until=Date.now()+timeout;while(Date.now()<until){if(await fn())return;await delay(200)}throw new Error('Timed out: '+description)}
let targets
await wait(async()=>{try{targets=await (await fetch(`http://127.0.0.1:${port}/json`)).json();return targets.some(t=>t.type==='page')}catch{return false}},'Chrome startup')
socket=new WebSocket(targets.find(t=>t.type==='page').webSocketDebuggerUrl)
await new Promise((resolve,reject)=>{socket.onopen=resolve;socket.onerror=reject})
let id=0
const pending=new Map(),errors=[]
socket.onmessage=event=>{const data=JSON.parse(event.data);if(data.id){const p=pending.get(data.id);if(p){pending.delete(data.id);data.error?p.reject(new Error(JSON.stringify(data.error))):p.resolve(data.result)}}else if(data.method==='Runtime.exceptionThrown')errors.push(data.params.exceptionDetails)}
function command(method,params={}){return new Promise((resolve,reject)=>{const call=++id;pending.set(call,{resolve,reject});socket.send(JSON.stringify({id:call,method,params}))})}
async function evaluate(expression){const data=await command('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});if(data.exceptionDetails)throw new Error(JSON.stringify(data.exceptionDetails));return data.result.value}
async function nav(label){await evaluate(`Array.from(document.querySelectorAll('nav button')).find(b=>b.textContent==='${label}').click()`);await delay(300)}
async function screenshot(name){const result=await command('Page.captureScreenshot',{format:'png',captureBeyondViewport:true});await writeFile(path.join(root,'docs',name),Buffer.from(result.data,'base64'))}
try{
 await command('Runtime.enable');await command('Page.enable');await command('Page.navigate',{url:'http://127.0.0.1:15173/'})
 await wait(()=>evaluate("document.body.innerText.includes('服务就绪')"),'App health')
 const evidence=JSON.parse(await readFile(path.join(root,'docs/p2-http-acceptance.json'),'utf8'))
 await evaluate(`(()=>{const select=document.querySelector('.projectbar select');select.value='${evidence.project_id}';select.dispatchEvent(new Event('change',{bubbles:true}))})()`)
 await delay(500);await nav('智能二创')
 await wait(()=>evaluate("!!document.querySelector('input[type=checkbox]')"),'Imported video selection')
 await evaluate("Array.from(document.querySelectorAll('button')).find(b=>b.textContent==='开始新批次').click()")
 const before=await evaluate(`fetch('/api/projects/${evidence.project_id}/tasks').then(r=>r.json()).then(ts=>ts.map(t=>t.id))`)
 await evaluate("(()=>{document.querySelector('input[type=checkbox]').click();const input=document.querySelectorAll('input[type=number]')[2];input.value='1';input.dispatchEvent(new Event('input',{bubbles:true}));})()")
 await screenshot('p2-editor.png')
 await evaluate("document.querySelector('form').requestSubmit()")
 await wait(()=>evaluate("document.body.innerText.includes('已确认 1 项任务入队')"),'Form submission')
 let rendered
 await wait(async()=>{const tasks=await evaluate(`fetch('/api/projects/${evidence.project_id}/tasks').then(r=>r.json())`);rendered=tasks.find(t=>!before.includes(t.id));if(rendered?.status==='failed')throw new Error(rendered.error);return rendered?.status==='succeeded'},'Browser-created render')
 await evaluate("document.querySelector('form').requestSubmit()")
 await wait(()=>evaluate("document.body.innerText.includes('已确认 1 项任务入队')"),'Duplicate submission response')
 await delay(300)
 const after=await evaluate(`fetch('/api/projects/${evidence.project_id}/tasks').then(r=>r.json())`)
 if(after.length!==before.length+1)throw new Error('Browser duplicate submission created extra tasks')
 await nav('批量生产');await wait(()=>evaluate("document.body.innerText.includes('100.0%')"),'Real queue state')
 await nav('质检与导出')
 await evaluate("Array.from(document.querySelectorAll('button')).find(b=>b.textContent==='预览成片').click()")
 await wait(()=>evaluate("document.querySelector('.output-preview video')?.videoWidth>0"),'Output video metadata')
 await evaluate("(async()=>{const video=document.querySelector('.output-preview video');video.muted=true;await video.play()})()")
 await wait(()=>evaluate("document.querySelector('.output-preview video')?.readyState>=2"),'Decoded video frame')
 await delay(400)
 await evaluate("document.querySelector('.output-preview video').pause()")
 const dimensions=await evaluate("({width:document.querySelector('.output-preview video').videoWidth,height:document.querySelector('.output-preview video').videoHeight})")
 await screenshot('p2-output.png')
 if(errors.length)throw new Error(JSON.stringify(errors))
 await writeFile(path.join(root,'docs/p2-browser-acceptance.json'),JSON.stringify({browser:'Installed Chrome headless via CDP',task_id:rendered.id,status:rendered.status,dimensions,javascript_errors:errors},null,2))
 console.log('Browser form -> persistent render -> output preview passed; no runtime JS exceptions.')
}finally{
 try{await command('Browser.close')}catch{}
 socket.close()
 browser.unref()
}
