<script setup lang="ts">
import { ref, useId } from 'vue'
import GuardianRules from './GuardianRules.vue'
import { api } from '../../services/api'

export interface ActorState {
  character_version_id:string; wardrobe_id:string; left_hand:string|null; right_hand:string|null; action:string; position:string
}
export interface ShotContract {
  visual:string; facts:Record<string,string>; source_image_asset_ids:string[];
  opening:ActorState[]; closing:ActorState[]; continuity_note:string
  screen_text?:ScreenTextContract|null
}
export interface ScreenTextContract {language:string;required:string[];forbidden:string[]}
const contract = defineModel<ShotContract|null>({ required:true })
const props = defineProps<{ characters:{version_id:string; title:string; version:number}[]; images:{id:string; name:string}[] }>()
const edges = [{id:'opening',label:'开场'},{id:'closing',label:'收尾'}] as const
const textRules = [{id:'required',label:'必现文字'},{id:'forbidden',label:'禁现文字'}] as const
const languages=ref<string[]|null>(null)
const languageList=useId()
const checking=ref(false)

async function loadLanguages() {
  if (checking.value || languages.value!==null) return
  checking.value=true
  try {
    const status=await api<{capabilities:{id:string;languages?:string[]}[]}>('/analysis/capabilities')
    languages.value=status.capabilities.find(item=>item.id==='ocr')?.languages || []
  } catch {
    languages.value=[]
  } finally { checking.value=false }
}

function setScreenText() {
  if (!contract.value) return
  contract.value.screen_text={language:'zh-Hans-CN',required:[''],forbidden:[]}
  void loadLanguages()
}

function enable() {
  contract.value = {visual:'',facts:{},source_image_asset_ids:[],opening:[],closing:[],continuity_note:''}
}

function add(edge:'opening'|'closing') {
  const list = contract.value?.[edge]
  if (!list) return
  const available = props.characters.find(character=>!list.some(state=>state.character_version_id===character.version_id))
  if (available) list.push({character_version_id:available.version_id,wardrobe_id:'',left_hand:null,right_hand:null,action:'',position:''})
}
</script>

<template>
  <details class="shot-contract">
    <summary>镜头合同与首尾状态 {{ contract ? '· 已设置' : '' }}</summary>
    <button v-if="!contract" type="button" @click="enable">设置镜头合同</button>
    <div v-else class="contract-form">
      <label>必须看到的画面<textarea v-model="contract.visual" required maxlength="1000"></textarea></label>
      <label>批准后可用的运镜源图<select v-model="contract.source_image_asset_ids" multiple>
        <option v-for="image in images" :key="image.id" :value="image.id">{{ image.name }}</option>
        <option v-for="id in contract.source_image_asset_ids.filter(id=>!images.some(image=>image.id===id))" :key="id" :value="id">{{ id }}</option>
      </select></label>
      <GuardianRules v-model="contract.facts" label="镜头剧情事实" prefix="fact" :limit="32" />
      <fieldset class="screen-text-rules">
        <legend>画面文字核验</legend>
        <button v-if="!contract.screen_text" type="button" @click="setScreenText">添加画面文字规则</button>
        <template v-else>
          <label>画面文字 OCR 语言<input v-model.trim="contract.screen_text.language" :list="languageList"
            pattern="[A-Za-z]{2,8}(-[A-Za-z0-9]{1,8})*" maxlength="35" required @focus="loadLanguages"></label>
          <datalist :id="languageList"><option v-for="language in languages || []" :key="language" :value="language"></option></datalist>
          <p v-if="checking" class="hint">正在读取本机 OCR 能力…</p>
          <p v-else-if="languages && !languages.includes(contract.screen_text.language)" class="hint">此语言未确认可用，候选将要求人工核验。</p>
          <div v-for="rule in textRules" :key="rule.id" class="screen-text-rules">
            <div v-for="(_,index) in contract.screen_text[rule.id]" :key="index" class="text-rule-line">
              <label>{{rule.label}} {{index+1}}<input v-model.trim="contract.screen_text[rule.id][index]" required maxlength="80"></label>
              <button type="button" @click="contract.screen_text[rule.id].splice(index,1)">移除</button>
            </div>
            <button type="button" :disabled="contract.screen_text[rule.id].length>=8"
              @click="contract.screen_text[rule.id].push('')">添加{{rule.label}}</button>
          </div>
          <button type="button" @click="contract.screen_text=null">关闭本镜头文字核验</button>
        </template>
      </fieldset>
      <fieldset v-for="edge in edges" :key="edge.id">
        <legend>{{ edge.label }}角色状态</legend>
        <div v-for="(state,index) in contract[edge.id]" :key="index" class="state-row">
          <label>固定角色<select v-model="state.character_version_id" required>
            <option v-if="!characters.some(person=>person.version_id===state.character_version_id)" :value="state.character_version_id">{{ state.character_version_id }}</option>
            <option v-for="character in characters" :key="character.version_id" :value="character.version_id">{{ character.title }} · v{{ character.version }}</option>
          </select></label>
          <label>服装键名<input v-model="state.wardrobe_id" maxlength="48" pattern="[a-z][a-z0-9_\-]{0,47}" required></label>
          <label>左手道具键名<input :value="state.left_hand ?? ''" maxlength="48" @input="state.left_hand=($event.target as HTMLInputElement).value || null"></label>
          <label>右手道具键名<input :value="state.right_hand ?? ''" maxlength="48" @input="state.right_hand=($event.target as HTMLInputElement).value || null"></label>
          <label>动作<input v-model="state.action" required maxlength="200"></label>
          <label>位置<input v-model="state.position" required maxlength="200"></label>
          <button type="button" @click="contract[edge.id].splice(index,1)">移除角色状态</button>
        </div>
        <button type="button" :disabled="contract[edge.id].length>=Math.min(characters.length,16)" @click="add(edge.id)">添加{{edge.label}}状态</button>
      </fieldset>
      <label>允许的衔接变化<textarea v-model="contract.continuity_note" maxlength="1000"></textarea></label>
      <button type="button" @click="contract=null">移除本草稿的镜头合同</button>
    </div>
  </details>
</template>

<style scoped>
.shot-contract { margin:12px 0; padding:12px }
.contract-form { display:grid; gap:10px }
.screen-text-rules { display:grid;gap:7px;min-width:0 }
.screen-text-rules button { justify-self:start }
.text-rule-line { display:grid;grid-template-columns:minmax(0,1fr) auto;gap:8px;align-items:end }
.state-row { display:grid; grid-template-columns:repeat(auto-fit,minmax(140px,1fr)); gap:8px; padding:8px 0; border-bottom:1px solid var(--line-soft) }
</style>
