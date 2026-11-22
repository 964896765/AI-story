<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { api } from '../../services/api'

const language=defineModel<string>({required:true})
const available=ref<string[]>([])
const controller=new AbortController()
onMounted(async()=>{
  try {
    const data=await api<{capabilities:{id:string;available:boolean;languages?:string[]}[]}>('/analysis/capabilities',
      {signal:controller.signal})
    const capability=data.capabilities.find(item=>item.id==='asr' && item.available)
    available.value=capability?.languages || []
  } catch (error) {
    if (!controller.signal.aborted) available.value=[]
  }
})
onBeforeUnmount(()=>controller.abort())
</script>

<template>
  <label>对白听写语言<select v-model="language">
    <option value="">关闭听写</option>
    <option v-if="language && !available.includes(language)" :value="language">{{language}} · 本机可用性未确认</option>
    <option v-for="locale in available" :key="locale" :value="locale">{{locale}} · Windows 本机</option>
  </select></label>
</template>
