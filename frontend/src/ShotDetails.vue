<script setup lang="ts">
import GuardianShot, { type ShotContract } from './components/production/GuardianShot.vue'

export interface Shot {
  shot_id?: string; number:number; description:string; dialogue:string; planned_duration:number
  scene_version_id:string|null; character_version_ids:string[]
  framing?:'wide'|'medium'|'close'|'detail'|null; angle?:string; movement?:string
  lighting?:string; composition?:string; wardrobe_and_props?:string; speaker_version_id?:string|null
  dialogue_ms?:number|null; emotion?:string; sound_cue?:string; transition?:string
  strategy?:'manual'|'still_motion'|'reference_video'|'generated_video'
  contract?:ShotContract|null
}
const props = defineProps<{ shot: Shot; characters:{version_id:string; title:string; version:number}[]; images:{id:string;name:string}[] }>()

function setContract(value:ShotContract|null) {
  props.shot.contract = value
  if (value && !props.shot.shot_id) props.shot.shot_id = crypto.randomUUID()
}
</script>

<template>
  <details class="shot-details">
    <summary>拍摄与声音设计</summary>
    <p v-if="shot.shot_id" class="mono">镜头 ID {{ shot.shot_id }}</p>
    <div class="editor-grid">
      <label>景别<select v-model="shot.framing">
        <option :value="null">未指定</option><option value="wide">全景</option><option value="medium">中景</option>
        <option value="close">近景</option><option value="detail">特写</option>
      </select></label>
      <label>机位角度<input v-model="shot.angle" maxlength="200"></label>
      <label>运镜<input v-model="shot.movement" maxlength="300"></label>
      <label>光线<input v-model="shot.lighting" maxlength="300"></label>
      <label>构图<input v-model="shot.composition" maxlength="500"></label>
      <label>服装与道具状态<input v-model="shot.wardrobe_and_props" maxlength="800"></label>
      <label>固定说话者<select v-model="shot.speaker_version_id">
        <option :value="null">未指定</option>
        <option v-for="character in characters.filter(item=>shot.character_version_ids.includes(item.version_id))"
          :key="character.version_id" :value="character.version_id">{{ character.title }} · v{{ character.version }}</option>
      </select></label>
      <label>对白预计用时（毫秒）<input :value="shot.dialogue_ms ?? ''" type="number" min="0" :max="Math.round(shot.planned_duration*1000)"
        @input="shot.dialogue_ms=($event.target as HTMLInputElement).value==='' ? null : Number(($event.target as HTMLInputElement).value)"></label>
      <label>情绪<input v-model="shot.emotion" maxlength="200"></label>
      <label>音响提示<input v-model="shot.sound_cue" maxlength="300"></label>
      <label>转场提示<input v-model="shot.transition" maxlength="200"></label>
      <label>制作方式<select v-model="shot.strategy">
        <option value="manual">人工制作</option><option value="still_motion">静图运镜</option>
        <option value="reference_video">参考视频</option><option value="generated_video">生成视频计划</option>
      </select></label>
    </div>
  </details>
  <GuardianShot :model-value="shot.contract ?? null" :images="images"
    :characters="characters.filter(item=>shot.character_version_ids.includes(item.version_id))"
    @update:model-value="setContract" />
</template>

<style scoped>
.shot-details { margin:12px 0; padding:12px }
</style>
