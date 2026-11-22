<script setup lang="ts">
import { ref } from 'vue'

const values = defineModel<Record<string,string>>({ required: true })
const props = defineProps<{ label:string; prefix:string; limit:number }>()
const error = ref('')

function add() {
  let index = 1
  while (`${props.prefix}_${index}` in values.value) index += 1
  values.value = { ...values.value, [`${props.prefix}_${index}`]: '' }
}

function rename(key:string, event:Event) {
  const input = event.target as HTMLInputElement
  const next = input.value.trim()
  if (next === key) return
  if (!/^[a-z][a-z0-9_-]{0,47}$/.test(next) || next in values.value) {
    input.value = key
    error.value = '键名需唯一，以小写字母开头，可包含数字、下划线和连字符。'
    return
  }
  error.value = ''
  values.value = Object.fromEntries(Object.entries(values.value).map(([name,value]) => [name===key ? next : name,value]))
}

function remove(key:string) {
  const next = { ...values.value }
  delete next[key]
  values.value = next
}
</script>

<template>
  <fieldset>
    <legend>{{ label }}</legend>
    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <div v-for="key in Object.keys(values)" :key="key" class="rules-row">
      <label>键名<input :value="key" maxlength="48" @change="rename(key,$event)"></label>
      <label>{{ label }}内容<input v-model="values[key]" required maxlength="1000"></label>
      <button type="button" :aria-label="`移除 ${key}`" @click="remove(key)">移除</button>
    </div>
    <button type="button" :disabled="Object.keys(values).length>=limit" @click="add">添加{{ label }}</button>
  </fieldset>
</template>

<style scoped>
.rules-row { display:grid; grid-template-columns:minmax(8rem,.6fr) minmax(10rem,1.4fr) auto; align-items:end; gap:8px; margin-bottom:8px }
@media (max-width:640px) { .rules-row { grid-template-columns:1fr } }
</style>
