import { AudioLines, Clapperboard, ClipboardCheck, Film, FolderOpen, LayoutDashboard, PanelsTopLeft,
  PenLine, Radio, Settings2, Sparkles, UsersRound } from 'lucide-vue-next'

export const destinations = {
  overview: { path: '/', label: '项目总览' },
  assets: { path: '/project/assets', label: '素材资产中心' },
  analysis: { path: '/project/analysis', label: '智能解析' },
  story: { path: '/creative/script', label: '漫剧定制' },
  adaptation: { path: '/creative/adaptation', label: '剧情改编' },
  characters: { path: '/creative/characters', label: '角色与场景' },
  storyboard: { path: '/creative/storyboard', label: '分镜编辑' },
  bible: { path: '/creative/bible', label: '故事圣经' },
  generation: { path: '/ai/candidates', label: '生成候选' },
  voice: { path: '/sound/voice', label: '配音与字幕' },
  timeline: { path: '/edit/timeline', label: '多轨时间轴' },
  video: { path: '/edit/video', label: '智能二创' },
  production: { path: '/production', label: '批量生产' },
  quality: { path: '/delivery/review', label: '质检与导出' },
  library: { path: '/delivery/library', label: '资源与交付' },
  operations: { path: '/operations', label: '运营中心' },
  system: { path: '/settings/system', label: '运行诊断' },
  models: { path: '/settings/models', label: '文本模型与预算' },
} as const

export type Destination = keyof typeof destinations

export const navigation = [
  { label: '工作空间', links: [
    { label: '项目总览', icon: LayoutDashboard, pages: ['overview'] },
    { label: '项目与素材', icon: FolderOpen, pages: ['assets', 'analysis'] },
  ] },
  { label: '创作', links: [
    { label: '剧本与创作', icon: PenLine, pages: ['story', 'adaptation'] },
    { label: '角色与场景', icon: UsersRound, pages: ['characters'] },
    { label: '分镜工作台', icon: PanelsTopLeft, pages: ['storyboard', 'bible'] },
    { label: 'AI 创作中心', icon: Sparkles, pages: ['generation'] },
    { label: '配音与声音', icon: AudioLines, pages: ['voice'] },
  ] },
  { label: '制作与交付', links: [
    { label: '剪辑与时间轴', icon: Film, pages: ['timeline', 'video'] },
    { label: '批量生产', icon: Clapperboard, pages: ['production'] },
    { label: '质检与交付', icon: ClipboardCheck, pages: ['quality', 'library'] },
  ] },
  { label: '管理', links: [
    { label: '发行与运营', icon: Radio, pages: ['operations'] },
    { label: '模型与系统设置', icon: Settings2, pages: ['system', 'models'] },
  ] },
] as const satisfies ReadonlyArray<{ label: string; links: ReadonlyArray<{ label: string; icon: object; pages: readonly Destination[] }> }>

export const workspaces = navigation.flatMap(group => [...group.links] as readonly {
  label: string; icon: object; pages: readonly Destination[]
}[])
