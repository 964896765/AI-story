<script setup lang="ts">
import { ref, watch } from 'vue'
import { api } from '../../services/api'
import { specPath, type ProductionSpec } from '../../types/productionSpec'
const props=defineProps<{projectId:string; disabled?:boolean}>()
const model=defineModel<string|null>({required:true})
const items=ref<ProductionSpec[]>([]), error=ref('')
watch(()=>props.projectId,async (id,_,onCleanup)=>{
  items.value=[];error.value=''
  if(!id)return
  const request=new AbortController()
  onCleanup(()=>request.abort())
  try {items.value=(await api<{items:ProductionSpec[]}>(specPath(id),{signal:request.signal})).items}
  catch (failure) {if(!request.signal.aborted)error.value=String(failure)}
},{immediate:true})
</script>
<template>
  <label v-if="items.length || model">固定制作规格
    <select v-model="model" :disabled="disabled">
      <option :value="null">沿用来源版本（无来源时留空）</option>
      <option v-if="model && !items.some(item=>item.id===model)" :value="model">固定历史规格 {{model}}</option>
      <option v-for="item in items" :key="item.id" :value="item.id">
        v{{item.version}} · {{item.settings.style || '画风待填'}} · {{item.missing_fields.length || item.compatibility_errors.length ? '需补全或调整' : '可用于本机生产'}}
      </option>
    </select>
  </label>
  <p v-if="error" class="error" role="alert">{{error}}</p>
</template>
