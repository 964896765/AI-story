import assert from 'node:assert/strict'
import { writeFile } from 'node:fs/promises'
import { join } from 'node:path'
import { api, base, evidenceDir, openChrome, post, wait } from './chrome-qa.mjs'

await wait(async()=>{
  try{return (await api('/health')).ready&&(await api('/queue')).workers.some(node=>node.online)}catch{return false}
},'isolated workbench')
await post('/projects',{name:'P14 本机诊断验收'})
const projectCount=(await api('/projects')).length
const {command,evaluate,contains,screenshot,errors,close}=await openChrome(19234)
const scripts="performance.getEntriesByType('resource').map(entry=>new URL(entry.name).pathname).filter(path=>path.endsWith('.js'))"
try{
  await wait(()=>contains('服务就绪'),'production build initialized')
  const initial=await evaluate(scripts)
  assert(initial.some(path=>/\/assets\/index-.+\.js$/.test(path)))
  assert(initial.every(path=>!path.includes('SystemStudio-')&&!path.includes('OperationsPage-')))
  await evaluate("document.querySelector('nav a[data-workspace=\"质检与交付\"]').focus()")
  await command('Input.dispatchKeyEvent',{type:'keyDown',key:'Tab',code:'Tab',windowsVirtualKeyCode:9})
  await command('Input.dispatchKeyEvent',{type:'keyUp',key:'Tab',code:'Tab',windowsVirtualKeyCode:9})
  assert.equal(await evaluate("document.activeElement.textContent.trim()"),'模型与设置')
  await command('Input.dispatchKeyEvent',{type:'keyDown',key:'Enter',code:'Enter',text:'\r',windowsVirtualKeyCode:13})
  await command('Input.dispatchKeyEvent',{type:'keyUp',key:'Enter',code:'Enter',windowsVirtualKeyCode:13})
  await wait(()=>evaluate("document.querySelector('[data-page=system]')!==null"),'settings loaded on keyboard navigation')
  await evaluate("document.querySelector('[data-page=system]').focus()")
  await command('Input.dispatchKeyEvent',{type:'keyDown',key:'Enter',code:'Enter',text:'\r',windowsVirtualKeyCode:13})
  await command('Input.dispatchKeyEvent',{type:'keyUp',key:'Enter',code:'Enter',windowsVirtualKeyCode:13})
  await wait(()=>contains('数据库迁移'),'diagnostics loaded on keyboard navigation')
  const additional=(await evaluate(scripts)).filter(path=>!initial.includes(path))
  assert(additional.some(path=>path.includes('SystemStudio-')))
  const observed=await api('/system/metrics')
  assert.equal(observed.database_revision,'0014')
  assert(observed.disk.free>0&&observed.workers.some(worker=>worker.online))
  assert.equal(observed.projects,projectCount)
  const blocked=await fetch(base+'/api/projects',{method:'POST',headers:{'Content-Type':'application/json','Sec-Fetch-Site':'cross-site'},
    body:JSON.stringify({name:'this request must be rejected'})})
  assert.equal(blocked.status,403)
  assert.match(blocked.headers.get('x-request-id'),/^[\da-f-]{36}$/)
  await screenshot('p14-system.png')
  assert.deepEqual(errors,[])
  await writeFile(join(evidenceDir,'p14-browser-acceptance.json'),JSON.stringify({
    checked_at:new Date().toISOString(),browser:'Installed Chrome headless',build:'Vite production preview',
    keyboard_navigation:true,first_load_script_count:initial.length,dynamic_diagnostics_script_loaded:true,
    logical_cpus:observed.logical_cpus,db_revision:observed.database_revision,disk_free_bytes:observed.disk.free,
    cross_site_write_blocked:true,request_id_attached:true,javascript_errors:errors,
  },null,2)+'\n')
  console.log('P14 browser: built bundle lazy loading, keyboard access, observed diagnostics and request protection verified.')
} catch(error){
  console.error(await evaluate('document.body.innerText.slice(-6500)'))
  throw error
} finally {await close()}
