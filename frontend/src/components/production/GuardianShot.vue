<script setup lang="ts">
import GuardianRules from './GuardianRules.vue'

export interface ActorState {
  character_version_id:string; wardrobe_id:string; left_hand:string|null; right_hand:string|null; action:string; position:string
}
export interface ShotContract {
  visual:string; facts:Record<string,string>; source_image_asset_ids:string[];
  opening:ActorState[]; closing:ActorState[]; continuity_note:string
}
const contract = defineModel<ShotContract|null>({ required:true })
const props = defineProps<{ characters:{version_id:string; title:string; version:number}[]; images:{id:string; name:string}[] }>()
const edges = [{id:'opening',label:'开场'},{id:'closing',label:'收尾'}] as const

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
.state-row { display:grid; grid-template-columns:repeat(auto-fit,minmax(140px,1fr)); gap:8px; padding:8px 0; border-bottom:1px solid var(--line-soft) }
</style>
