import type { Destination } from './navigation'
import type { ProjectOverview } from '../types/workbench'

export const capabilityLabels = {
  local:'本机可执行', manual:'人工／规则', simulated:'模拟已验收', partial:'部分实现', pending:'待接入',
} as const

type Step = readonly [page: Destination, title: string, input: string, action: string, output: string, capability: keyof typeof capabilityLabels]

export const phases = [
  { title: '立项与指挥', steps: [
    ['assets','创建项目与授权登记','原创创意或已授权来源','新建项目，把创意填入项目说明，登记素材及授权来源。','可追溯的项目与素材','local'],
    ['wizard','确定制作规格','项目与创意','在本阶段制作备注记录集数、单集时长、画风和画幅，供制定计划时引用。','本机规格备注','partial'],
    ['models','配置模型与预算','制作规格与费用上限','选择文本供应商或离线模拟，核对费率和额度。Codex 与媒体供应商可保存接入草稿。','供应商配置与预算记录','partial'],
    ['director','制定执行计划','目标、规格和已具备的固定版本','记录制作指令并选择本机工作流。固定时间轴、整剧批次和交付可保存待批执行计划。','待确认的计划与交接事项','partial'],
  ] },
  { title: '小说与剧本', steps: [
    ['story','保存原稿','小说、现有剧本或原创创意','粘贴原稿或创意文本，记录授权并保存版本。','固定原稿版本','local'],
    ['adaptation','剧情解析与改编','固定原稿、模型配置与改编目标','从原稿进入改编。可用离线模拟验证流程；真实创作须经过配置和授权。','待审核改编稿','simulated'],
    ['story','全剧大纲与分集','改编稿或自编大纲','人工整理主线，或按段落和字数规则拆分后手工核对，保存分集记录。','固定分集版本','manual'],
    ['story','分集剧本与审核','分集、台词与剧本版本','人工核对台词和衔接，选定剧本版本供故事圣经引用。独立逐集签审待补齐。','供故事圣经引用的剧本','partial'],
  ] },
  { title: '统一资产', steps: [
    ['bible','建立故事圣经','固定剧本、分集和分镜引用','记录剧情事实、世界规则与统一画风；分镜补齐后提交批准。','故事圣经草稿','local'],
    ['characters','人物定妆与声音','人物设定、授权参考图及音色','保存角色、服装、参考图和声音设定。','可引用角色版本','partial'],
    ['characters','场景、道具与美术','分集场景和已授权素材','保存场景，按需在故事圣经补充道具和风格。','场景和风格版本','manual'],
    ['bible','核对固定版本','剧本、角色、场景和分镜版本','核对故事圣经引用的版本是否与本次制作一致。','可复核的固定引用','local'],
  ] },
  { title: '分镜导演', steps: [
    ['storyboard','编写分镜','固定分集和场景','新增镜头，填写内容、时长、角色和场景。','分镜版本','manual'],
    ['guardian','检查动作与空间衔接','故事圣经与分镜版本','核对角色首尾状态、道具和剧情事实，修正阻断项。','连续性报告','manual'],
    ['models','选择模型与输入规格','镜头要求、参考图与时长','保存模型输入要求并核对供应商状态。媒体模型的报价与执行尚未贯通。','模型选择和镜头输入要求','partial'],
    ['bible','批准镜头与制作计划','通过检查的故事圣经和分镜','批准固定版本，再进入生成候选。','可提交生产的批准计划','local'],
  ] },
  { title: '生成与候选', steps: [
    ['generation','图片与关键帧','角色参考、场景和镜头要求','先导入自有或授权关键帧。本机可用已有图片制作运镜候选。','授权关键帧','pending'],
    ['generation','审核候选一致性','镜头合同、参考图与候选','对照角色、服装、场景并记录证据，再决定是否采纳。','已审核的镜头素材','manual'],
    ['generation','AI 动态视频','固定镜头、关键帧和授权预算','可先制作 FFmpeg 静图运镜候选。外部动态视频需接入供应商。','视频候选','pending'],
    ['voice','配音与字幕','批准分镜、对白和本机音色','生成并试听本机对白，同步字幕；音乐音效可导入时间轴。','配音和字幕素材','local'],
  ] },
  { title: '后期与交付', steps: [
    ['guardian','镜头质检与汇合','候选、字幕和镜头审核记录','补齐证据，按问题定位并返工受影响镜头。','可用于剪辑的镜头','manual'],
    ['timeline','多轨剪辑与合成','已采纳的镜头、音轨和字幕','固定各集时间轴，校对片段、字幕和混音。','可提交渲染的时间轴','local'],
    ['production','渲染与成片复检','分集时间轴和质检规则','提交本机生产，核对阻断和告警，按分集返工。','通过质检的整剧批次','local'],
    ['library','终审、交付与归档','通过质检的成片和来源授权','核对渠道授权并生成 ZIP，在运营中心登记人工发行。','可验证的多集交付包','local'],
  ] },
] as const satisfies readonly {title:string; steps:readonly Step[]}[]

export const workflowSteps = phases.flatMap((phase, index) =>
  (phase.steps as readonly Step[]).map(([page, title, input, action, output, capability], offset) =>
    ({ number: index*4+offset+1, phase:index+1, page, title, input, action, output, capability })))

export function suggestedStep(data: ProjectOverview) {
  const counts = data.story_counts
  const batch = data.latest_run
  if (data.latest_delivery?.status === 'succeeded') return { step: 24, label: '查看已验证交付包', query: {run: data.latest_delivery.run_id} }
  if (batch?.status === 'passed') return { step: 24, label: '核对授权并创建交付包', query: {run: batch.id} }
  if (batch) return { step: 23, label: '查看当前批次与质检', query: {run: batch.id} }
  if (data.draft_reviews.length) return { step: 6, label: '审核改编稿', query: {call: data.draft_reviews[0].id} }
  if (counts.timeline) return { step: 23, label: '打开整剧生产', query: {} }
  if (data.workflow?.adopted_candidates) return { step: 22, label: '编排多轨时间轴', query: {} }
  if (data.workflow?.approved_series_id) return { step: 18, label: '制作并审核镜头候选', query: {} }
  if (counts.story_bible) return { step: 16, label: '核对并批准故事圣经', query: {} }
  if (counts.storyboard) return { step: 9, label: '建立故事圣经', query: {} }
  if (counts.script && counts.episode && counts.character && counts.scene) return { step: 13, label: '编写分镜', query: {} }
  if (counts.script && counts.episode) return { step: 10, label: '建立角色与场景', query: {} }
  if (counts.script) return { step: 7, label: '整理分集', query: {} }
  if (counts.novel || counts.episode) return { step: 6, label: '从固定原稿开始改编', query: {source:data.workflow?.adaptation_source_id || undefined} }
  return { step: 5, label: '保存小说或原创创意', query: {} }
}
