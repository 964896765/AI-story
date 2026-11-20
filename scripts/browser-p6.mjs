import { execFileSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { writeFile, readFile } from 'node:fs/promises'
import { join } from 'node:path'
import assert from 'node:assert/strict'
import { api, base, evidenceDir, openChrome, post, qaRoot, wait } from './chrome-qa.mjs'

await wait(async () => {
  try { return (await api('/health')).ready && (await api('/queue')).workers.some(worker => worker.online) } catch { return false }
}, 'isolated app')
const scriptText = '灯塔熄灭前，请在船边等我。'
const project = await post('/projects', { name: 'P6 自有样本浏览器验收' })
const projectPath = '/projects/' + project.id
const localSrt = join(qaRoot, 'self-authored.srt')
const srtTime = ms => `00:00:01,${String(ms).padStart(3,'0')}`
const moreCues = Array.from({length:51}, (_, index) => {
  const start = 510 + index*9
  return `${index+2}\n${srtTime(start)} --> ${srtTime(start+7)}\n验收字幕 ${index+2}\n`
})
await writeFile(localSrt, ['1\n00:00:00,500 --> 00:00:01,500\n'+scriptText+'\n',...moreCues].join('\n'))
const localVideo = join(qaRoot, 'p6-owned.mkv')
execFileSync('ffmpeg', ['-v','error','-f','lavfi','-i','color=black:s=320x240:r=24:d=1',
  '-f','lavfi','-i','color=white:s=320x240:r=24:d=1',
  '-f','lavfi','-i','sine=frequency=440:duration=2',
  '-f','lavfi','-i','sine=frequency=880:duration=2',
  '-i',localSrt,'-filter_complex','[0:v][1:v]concat=n=2:v=1:a=0[v]',
  '-map','[v]','-map','2:a','-map','3:a','-map','4:s',
  '-c:v','libx264','-c:a','pcm_s16le','-c:s','srt',localVideo], {timeout:30000})
const original = await readFile(localVideo)
const sha256 = bytes => createHash('sha256').update(bytes).digest('hex')
const form = new FormData()
form.set('file', new Blob([original]), '灯塔样本.mkv')
form.set('authorization','自编短句及生成的色块、音调，用于本地回归')
const asset = await api(projectPath + '/assets', {method:'POST',body:form})
assert.equal(asset.sha256, sha256(original))
const route = '/analysis' + projectPath + '/assets/' + asset.id + '/tasks'

const {command,evaluate,contains,click,setField,screenshot,errors,close} = await openChrome(19226)
try {
  await wait(() => contains('服务就绪'), 'app loaded')
  await setField('当前项目',project.id)
  await click('智能解析')
  await wait(() => contains('灯塔样本.mkv'), 'material selected')
  for (const operation of ['inspect','split','remux','transcode','frames','scenes','subtitles','waveform']) {
    await wait(() => evaluate(`(() => {
      const box = document.querySelector('.analysis-choices input[value=${operation}]')
      if (!box || box.disabled) return false
      if (!box.checked) box.click()
      return box.checked
    })()`), 'selected step: '+operation)
  }
  assert.equal(await evaluate("document.querySelectorAll('.analysis-choices input:checked').length"),8)
  await click('提交本地解析')
  await wait(() => contains('已提交 8 项解析任务'), 'all operations submitted')
  let tasks
  await wait(async () => {
    tasks=await api(route)
    for (const task of tasks) if (task.status === 'failed') throw new Error(task.error)
    return tasks.length===8 && tasks.every(task => task.status==='succeeded')
  }, 'worker processed all jobs', 55000)
  const results=Object.fromEntries(await Promise.all(tasks.map(async task => [
    task.parameters.operation, await api('/analysis/tasks/'+task.id+'/result'),
  ])))
  assert.deepEqual(results.inspect.media.streams.map(stream => stream.codec_type), ['video','audio','audio','subtitle'])
  assert.equal(results.split.artifacts.length,4)
  assert.equal(results.scenes.shots.length,2)
  assert.equal(results.scenes.shots[1].start_us,1000000)
  assert.equal(results.subtitles.subtitle_tracks[0].cues[0].text,scriptText)
  assert(results.waveform.bins.some(bin => bin>0))
  await click('MP4 转码 / 代理')
  await click('预览代理')
  await wait(() => evaluate("document.querySelector('video')?.readyState >= 1"), 'Chrome decoded proxy metadata')
  const url='/api/analysis/tasks/'+results.transcode.task_id+'/artifacts/0'
  const proxy=await fetch(base+url,{headers:{Range:'bytes=0-99'}})
  assert.equal(proxy.status,206)
  assert.equal((await proxy.arrayBuffer()).byteLength,100)
  await evaluate("Array.from(document.querySelectorAll('h2')).find(n=>n.textContent==='代理预览').scrollIntoView({block:'center'})")
  await screenshot('p6-analysis.png')

  await evaluate(`(async () => {
    for (const box of document.querySelectorAll('.analysis-choices input:checked:not([value="waveform"])')) {
      box.click()
      await Promise.resolve()
    }
    document.querySelector('.analysis-options details').open = true
  })()`)
  await setField('波形与静音源流','2')
  await click('提交本地解析')
  let selectedWave
  await wait(async () => {
    const rows=await api(route)
    selectedWave=rows.find(row=>row.parameters.operation==='waveform' && row.parameters.stream===2)
    if (selectedWave?.status==='failed') throw new Error(selectedWave.error)
    return selectedWave?.status==='succeeded'
  },'worker analyzed second audio stream')
  const wave=await api('/analysis/tasks/'+selectedWave.id+'/result')
  assert.equal(wave.stream_index,2)
  await wait(() => evaluate("document.querySelector('.analysis-result')?.textContent.includes('流 2') && !!document.querySelector('canvas')"),'second track waveform displayed')
  await click('字幕')
  await wait(() => contains('52 条'),'all cues reachable')
  await click('下一页')
  await wait(() => contains('验收字幕 52'),'last cue paginated')
  await click('上一页')
  await evaluate("document.querySelector('.cue-list button').click()")
  await wait(() => evaluate("document.querySelector('.active-caption')?.textContent.includes('灯塔熄灭前')"),'preview shows selected cue')
  await evaluate("document.querySelectorAll('.shot-marker')[1].click()")
  await wait(() => evaluate("Math.abs(document.querySelector('video').currentTime - 1) < .03"),'shot marker seeks real proxy')
  await screenshot('v3-02-analysis-desktop.png')
  const reviewLink = await evaluate("document.querySelector('.analysis-link').href")
  const link = new URL(reviewLink)
  assert.equal(link.searchParams.get('asset'),asset.id)
  assert.equal(link.searchParams.get('task'),results.subtitles.task_id)
  assert.equal(link.searchParams.get('at'),'1000000')
  assert.equal(link.searchParams.get('preview'),results.transcode.task_id)
  const [replacement] = await post('/analysis'+projectPath+'/tasks',{
    asset_id:asset.id, steps:[{operation:'transcode',crf:24}], idempotency_key:'browser-replacement-proxy',
  })
  await wait(async () => (await api(route+'/'+replacement.id)).status === 'succeeded','newer proxy completed')
  await command('Page.navigate',{url:reviewLink})
  await wait(() => evaluate(`(() => {
    const player=document.querySelector('video')
    return document.querySelector('.cue-list') && player?.readyState>=1 &&
      player.currentSrc.endsWith(${JSON.stringify(url)}) && Math.abs(player.currentTime-1)<.03
  })()`),'deep link restores selected task and exact older proxy')
  await command('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true})
  await wait(() => evaluate("window.innerWidth===390 && document.documentElement.scrollWidth<=390"),'mobile fits viewport')
  await screenshot('v3-02-analysis-mobile.png')
  await command('Emulation.clearDeviceMetricsOverride')

  await wait(() => contains('快照证据 · 8 项'), 'browser synchronized all eight results')
  await setField('审核说明','浏览器验收，人工确认镜头时间和字幕归属。')
  await click('保存审核快照')
  await wait(() => contains('已保存审核快照 v1'), 'review snapshot persisted')
  const [revision] = await api('/analysis/assets/'+asset.id+'/revisions')
  const snapshot = await api('/analysis/revisions/'+revision.id)
  assert.deepEqual(snapshot.payload.subtitle_cues[0].shots,[1,2])
  await setField('采纳说明','同意将人工核对的自有字幕保存为剧本。')
  await setField('审核稿标题','灯塔来信 · 审核稿')
  await click('载入选定字幕或人工转写')
  await evaluate("Array.from(document.querySelectorAll('button')).find(b=>b.textContent==='保存 P4 剧本并打开 P5 改编').scrollIntoView({block:'center'})")
  await screenshot('p6-review.png')
  await evaluate("Array.from(document.querySelectorAll('button')).find(b=>b.textContent==='保存 P4 剧本并打开 P5 改编').focus()")
  await command('Input.dispatchKeyEvent',{type:'keyDown',key:'Enter',code:'Enter',text:'\r',windowsVirtualKeyCode:13})
  await command('Input.dispatchKeyEvent',{type:'keyUp',key:'Enter',code:'Enter',windowsVirtualKeyCode:13})
  await wait(() => contains('固定原稿 灯塔来信 · 审核稿'), 'adopted script reused by P5')
  const entities=await api(projectPath+'/story/entities')
  const adopted=await api('/story/versions/'+entities.items.find(item=>item.kind==='script').version_id)
  assert.equal(adopted.provenance.analysis_revision_id,revision.id)
  assert.equal(adopted.content.body.split('\n')[0],scriptText)
  assert(adopted.content.body.includes('验收字幕 52'))
  const source=await fetch(base+'/api/assets/'+asset.id+'/media')
  assert.equal(sha256(Buffer.from(await source.arrayBuffer())), asset.sha256)
  assert.deepEqual(errors,[])
  await writeFile(join(evidenceDir,'p6-browser-acceptance.json'),JSON.stringify({
    checked_at:new Date().toISOString(),browser:'Installed Chrome headless',operations:Object.keys(results),
    streams:results.inspect.media.streams.length,split_files:results.split.artifacts.length,
    proxy_metadata_decoded:true,range_status:proxy.status,shots:results.scenes.shots,
    source_sha256:asset.sha256,source_hash_verified:true,review_revision_id:revision.id,
    reviewed_script_version:adopted.version_id,keyboard_adoption:true,real_external_calls:0,
    js_errors:errors,
  },null,2)+'\n')
  await writeFile(join(evidenceDir,'v3-02-analysis-browser.json'),JSON.stringify({
    checked_at:new Date().toISOString(), operation_count:Object.keys(results).length,
    subtitle_cues:results.subtitles.subtitle_tracks[0].cues.length,
    browser_seek_us:1000000, restored_proxy_from_link:true, mobile_width:390, selected_audio_stream:wave.stream_index,
    immutable_review_revision:revision.id, fixed_script_version:adopted.version_id,
    source_hash_verified:true, paid_model_calls:0, js_errors:errors,
  },null,2)+'\n')
  console.log('P6 browser: eight local FFmpeg steps, seekable proxy, immutable review and P5 handoff passed.')
} catch (error) {
  console.error(await evaluate('document.body.innerText.slice(-6000)'))
  throw error
} finally { await close() }
