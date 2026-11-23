<script setup lang="ts">
import { ref, watch } from 'vue'
import { api } from '../../services/api'
import { specPath, type ProductionSpec } from '../../types/productionSpec'
const props=defineProps<{projectId:string; versionId?:string|null}>()
const spec=ref<ProductionSpec|null>(null), error=ref('')
watch(()=>[props.projectId,props.versionId] as const,async ([project,id],_,onCleanup)=>{
  spec.value=null;error.value=''
  if(!project || !id)return
  const request=new AbortController()
  onCleanup(()=>request.abort())
  try {spec.value=await api<ProductionSpec>(specPath(project)+'/'+encodeURIComponent(id),{signal:request.signal})}
  catch (failure) {if(!request.signal.aborted)error.value=String(failure)}
},{immediate:true})
</script>
<template>
  <p v-if="spec" class="hint" data-spec-reference>
    <RouterLink :to="{name:'wizard',query:{project:projectId,step:1,spec:spec.id}}">固定制作规格 v{{spec.version}}</RouterLink>
    · {{spec.settings.profile || '画幅未填'}} · {{ spec.settings.width && spec.settings.height ? `${spec.settings.width} × ${spec.settings.height}` : '分辨率未填' }}
    <span v-if="spec.settings.fps"> · {{spec.settings.fps}} fps</span>
  </p>
  <p v-else-if="error" class="error" role="alert">{{error}}</p>
</template>
