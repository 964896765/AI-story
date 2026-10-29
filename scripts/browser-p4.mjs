// Installed Chrome + native CDP; no dependencies or browser downloads.
import {spawn} from 'node:child_process'
import {readFile,writeFile} from 'node:fs/promises'
import path from 'node:path'
import {fileURLToPath} from 'node:url'
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..'),port=19224
try{await fetch(`http://127.0.0.1:${port}/json/version`);throw new Error('QA port occupied')}catch(e){if(e.message==='QA port occupied')throw e}
const browser=spawn('C:/Program Files/Google/Chrome/Application/chrome.exe',['--headless=new','--disable-gpu',`--remote-debugging-port=${port}`,'--remote-debugging-address=127.0.0.1',`--user-data-dir=${path.join(root,'data/browser-p4')}`,'--window-size=1500,1100','--no-first-run','about:blank'],{windowsHide:true,stdio:'ignore'})
const delay=ms=>new Promise(r=>setTimeout(r,ms))
async function wait(fn,label,timeout=30000){const end=Date.now()+timeout;while(Date.now()<end){if(await fn())return;await delay(200)}throw new Error('Timed out: '+label)}
let targets
await wait(async()=>{try{targets=await(await fetch(`http://127.0.0.1:${port}/json`)).json();return targets.some(t=>t.type==='page')}catch{return false}},'Chrome startup')
const socket=new WebSocket(targets.find(t=>t.type==='page').webSocketDebuggerUrl)
await new Promise((resolve,reject)=>{socket.onopen=resolve;socket.onerror=reject})
const pending=new Map(),errors=[];let nextId=0
socket.onmessage=e=>{const data=JSON.parse(e.data);if(data.id){const call=pending.get(data.id);if(call){pending.delete(data.id);data.error?call.reject(new Error(JSON.stringify(data.error))):call.resolve(data.result)}}else if(data.method==='Runtime.exceptionThrown')errors.push(data.params.exceptionDetails)}
function command(method,params={}){return new Promise((resolve,reject)=>{const id=++nextId;pending.set(id,{resolve,reject});socket.send(JSON.stringify({id,method,params}))})}
async function evaluate(expression){const data=await command('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});if(data.exceptionDetails)throw new Error(JSON.stringify(data.exceptionDetails));return data.result.value}
async function nav(label){await evaluate(`Array.from(document.querySelectorAll('nav button')).find(b=>b.textContent==='${label}').click()`);await delay(250)}
async function choose(kind,title){await evaluate(`(()=>{const select=document.querySelector('.story-library select');select.value='${kind}';select.dispatchEvent(new Event('change',{bubbles:true}))})()`);await delay(200);await evaluate(`Array.from(document.querySelectorAll('.story-item')).find(b=>b.textContent.includes(${JSON.stringify(title)})).click()`);await wait(()=>evaluate(`document.querySelector('.story-editor input')?.value===${JSON.stringify(title)}`),'Creative asset load');await delay(300)}
async function field(label,value){await evaluate(`(()=>{const container=Array.from(document.querySelectorAll('.story-editor label')).find(l=>l.childNodes[0]?.textContent.trim()===${JSON.stringify(label)});const input=container.querySelector('input,textarea');input.value=${JSON.stringify(value)};input.dispatchEvent(new Event('input',{bubbles:true}))})()`)}
async function screenshot(name){const result=await command('Page.captureScreenshot',{format:'png',captureBeyondViewport:true});await writeFile(path.join(root,'docs',name),Buffer.from(result.data,'base64'))}
try{
 await command('Runtime.enable');await command('Page.enable');await command('Page.navigate',{url:'http://127.0.0.1:15173/'})
 await wait(()=>evaluate("document.body.innerText.includes('服务就绪')"),'App ready')
 const evidence=JSON.parse(await readFile(path.join(root,'docs/p4-http-acceptance.json'),'utf8'))
 await evaluate(`(()=>{const select=document.querySelector('.projectbar select');select.value='${evidence.project_id}';select.dispatchEvent(new Event('change',{bubbles:true}))})()`);await delay(400)
 await nav('漫剧定制');await wait(()=>evaluate("!!document.querySelector('.story-library select')"),'Creative studio')
 await choose('script','归城第一场')
 await field('剧本正文','浏览器真实编辑的剧本。\n\n这段内容经过人工编写，没有调用模型。')
 await evaluate("document.querySelector('.story-editor form').requestSubmit()")
 await wait(()=>evaluate("document.body.innerText.includes('已保存数据库版本 v2')"),'Script v2 persisted')
 await evaluate("Array.from(document.querySelectorAll('button')).find(b=>b.textContent==='与正在查看的版本比较').click()")
 await wait(()=>evaluate("document.querySelector('.log-tail')?.textContent.includes('浏览器真实编辑')"),'Version diff')
 await evaluate("Array.from(document.querySelectorAll('.version-list button')).find(b=>b.textContent.startsWith('v1 ')).click()")
 await wait(()=>evaluate("document.body.innerText.includes('当前为历史版本')"),'Historical version')
 await evaluate("Array.from(document.querySelectorAll('button')).find(b=>b.textContent==='从此历史追加恢复版本').click()")
 await wait(()=>evaluate("document.body.innerText.includes('已追加恢复版本')"),'Append-only restore')
 await screenshot('p4-history.png')
 await choose('character','林舟')
 const unsaved='浏览器尚未保存的外貌草稿：黑发，青色外套。'
 await field('外貌与固定特征',unsaved);await delay(600)
 await command('Page.reload')
 await wait(()=>evaluate("document.body.innerText.includes('服务就绪')"),'Reloaded app')
 await nav('漫剧定制')
 await wait(()=>evaluate(`Array.from(document.querySelectorAll('.story-editor textarea')).some(t=>t.value===${JSON.stringify(unsaved)})`),'Unsaved draft restored after reload')
 await evaluate("document.querySelector('.story-editor form').requestSubmit()")
 await wait(()=>evaluate("document.body.innerText.includes('已保存数据库版本 v4')"),'Character v4')
 await choose('generation_plan','后续文本模型输入计划')
 await evaluate("Array.from(document.querySelectorAll('button')).find(b=>b.textContent==='查看模型接入状态').click()")
 await wait(()=>evaluate("document.body.innerText.includes('费用未知')"),'Unknown estimate is explicit')
 await screenshot('p4-plan.png')
 await choose('storyboard','归城分镜计划');await screenshot('p4-storyboard.png')
 await evaluate("Array.from(document.querySelectorAll('button')).find(b=>b.textContent==='引用此版本创建剪辑批次').click()")
 await wait(()=>evaluate(`document.body.innerText.includes('${evidence.storyboard_version_id}')&&!!document.querySelector('input[type=checkbox]')`),'Pinned creative production')
 const before=await evaluate(`fetch('/api/projects/${evidence.project_id}/tasks').then(r=>r.json()).then(ts=>ts.map(t=>t.id))`)
 await evaluate("(()=>{document.querySelector('input[type=checkbox]').click();const input=document.querySelectorAll('input[type=number]')[2];input.value='1';input.dispatchEvent(new Event('input',{bubbles:true}));document.querySelector('form').requestSubmit()})()")
 await wait(()=>evaluate("document.body.innerText.includes('已确认 1 项任务入队')"),'Production submitted')
 let result
 await wait(async()=>{const tasks=await evaluate(`fetch('/api/projects/${evidence.project_id}/tasks').then(r=>r.json())`);result=tasks.find(t=>!before.includes(t.id));if(result?.status==='failed')throw new Error(result.error);return result?.status==='succeeded'},'Real story-linked render')
 if(result.story_version_id!==evidence.storyboard_version_id)throw new Error('Production reference lost')
 if(errors.length)throw new Error(JSON.stringify(errors))
 await writeFile(path.join(root,'docs/p4-browser-acceptance.json'),JSON.stringify({browser:'Installed Chrome headless',script_restore_version:3,character_version:4,draft_reload_verified:true,story_version_id:result.story_version_id,task_id:result.id,status:result.status,javascript_errors:errors},null,2))
 console.log('P4 browser: real edit/restore, draft reload, disabled model state and pinned video batch passed.')
}finally{try{await command('Browser.close')}catch{}socket.close();browser.unref()}
