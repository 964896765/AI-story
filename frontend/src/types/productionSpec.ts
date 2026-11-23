export interface ProductionSettings {
  episode_count:number|null; episode_duration_ms:number|null; style:string
  profile:'portrait'|'landscape'|'square'|null; width:number|null; height:number|null; fps:number|null
  platform:string; region:string; budget_cents:number|null; budget_currency:'CNY'|'USD'
  restrictions:string; imported_note:string
}

export interface ProductionSpecRef {id:string;version:number;sha256:string}
export interface ProductionSpec extends ProductionSpecRef {
  settings:ProductionSettings; created_at:string; missing_fields:string[]; compatibility_errors:string[]
  restored_from_id:string|null
}

export const specPath=(projectId:string)=>`/projects/${encodeURIComponent(projectId)}/production-specs`
export const specLabels:Record<keyof ProductionSettings,string>={
  episode_count:'计划集数',episode_duration_ms:'单集目标时长（毫秒）',style:'画风与美术',
  profile:'画幅',width:'输出宽度',height:'输出高度',fps:'输出帧率',
  platform:'发行平台标识',region:'发行地域',budget_cents:'制作预算（分）',budget_currency:'币种',
  restrictions:'制作限制',imported_note:'导入的浏览器备注',
}
