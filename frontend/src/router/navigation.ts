import { AudioLines, BookOpen, BrainCircuit, Clapperboard, Film, Image, Layers3, LayoutDashboard,
  Settings2, ShieldCheck, UsersRound, WandSparkles } from 'lucide-vue-next'

export const destinations = {
  overview: { path: '/', label: '项目总览' },
  director: { path: '/director', label: 'AI 总导演' },
  wizard: { path: '/wizard', label: '六步创作向导' },
  assets: { path: '/project/assets', label: '素材资产中心' },
  analysis: { path: '/project/analysis', label: '智能解析' },
  story: { path: '/creative/script', label: '小说与剧本' },
  adaptation: { path: '/creative/adaptation', label: '剧情改编' },
  characters: { path: '/creative/characters', label: '角色与场景' },
  storyboard: { path: '/creative/storyboard', label: '分镜编辑' },
  bible: { path: '/creative/bible', label: '故事圣经' },
  generation: { path: '/ai/candidates', label: '生成候选' },
  voice: { path: '/sound/voice', label: '配音与字幕' },
  timeline: { path: '/edit/timeline', label: '多轨时间轴' },
  video: { path: '/edit/video', label: '智能二创' },
  production: { path: '/production', label: '生产调度' },
  quality: { path: '/delivery/review', label: '质检与导出' },
  guardian: { path: '/delivery/guardian', label: 'Guardian 质量控制' },
  library: { path: '/delivery/library', label: '资源与交付' },
  operations: { path: '/operations', label: '运营中心' },
  system: { path: '/settings/system', label: '运行诊断' },
  models: { path: '/settings/models', label: '模型接入与预算' },
} as const

export type Destination = keyof typeof destinations

export const navigation = [
  { label: 'Workspace', links: [
    { label: '项目总览', icon: LayoutDashboard, pages: ['overview'] },
    { label: 'AI 总导演', icon: BrainCircuit, pages: ['director'] },
    { label: '创作向导', icon: WandSparkles, pages: ['wizard'] },
  ] },
  { label: 'Create', links: [
    { label: '小说与剧本', icon: BookOpen, pages: ['story', 'adaptation'] },
    { label: '角色与场景', icon: UsersRound, pages: ['characters', 'assets', 'analysis'] },
    { label: '分镜工作台', icon: Film, pages: ['storyboard', 'bible'] },
  ] },
  { label: 'Production', links: [
    { label: 'AI 图片与视频', icon: Image, pages: ['generation'] },
    { label: '配音与声音', icon: AudioLines, pages: ['voice'] },
    { label: '剪辑与时间轴', icon: Layers3, pages: ['timeline', 'video'] },
  ] },
  { label: 'Manage', links: [
    { label: '生产调度', icon: Clapperboard, pages: ['production'] },
    { label: '质检与交付', icon: ShieldCheck, pages: ['guardian', 'quality', 'library', 'operations'] },
    { label: '模型与设置', icon: Settings2, pages: ['models', 'system'] },
  ] },
] as const satisfies ReadonlyArray<{ label: string; links: ReadonlyArray<{ label: string; icon: object; pages: readonly Destination[] }> }>

export const workspaces = navigation.flatMap(group => [...group.links] as readonly {
  label: string; icon: object; pages: readonly Destination[]
}[])
