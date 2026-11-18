<script setup lang="ts">
import { reactive, ref } from 'vue'
const emit = defineEmits<{ saved: [] }>()
const busy = ref(false), error = ref(''), notice = ref('')
// Real configurations deliberately start without prices or verified billing claims.
const form = reactive({ label: '', base_url: '', model: '', secret_env: 'AI_STORY_TEXT_API_KEY', currency: 'CNY',
  input_per_million: '', output_per_million: '', input_token_limit: 8192, output_token_limit: 2048,
  price_source: '', billing_verified: false, rejection_is_nonbillable: false,
  token_parameter: 'max_completion_tokens', response_format: 'json_schema', timeout_seconds: 60 })
async function save() {
  busy.value = true; error.value = ''; notice.value = ''
  try {
    const { label, ...settings } = form
    const response = await fetch('/api/text/providers', { method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ label, kind: 'openai_compatible', enabled: false, settings: { ...settings,
        input_per_million: settings.input_per_million || null, output_per_million: settings.output_per_million || null } }) })
    const body = await response.json()
    if (!response.ok) throw new Error(typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail))
    notice.value = '配置已保存为禁用状态，未进行联网测试。密钥只在本机环境变量配置。'
    emit('saved')
  } catch (failure) { error.value = String(failure) } finally { busy.value = false }
}
</script>
<template>
  <details>
    <summary>配置真实文本供应商（保存时禁用）</summary>
    <p class="hint">本阶段授权预算为 0。保存配置不会发出请求。费率留空即未知；核验计费条款不能替代后续明确调用授权。</p>
    <p v-if="error" class="error" role="alert">{{ error }}</p><p v-if="notice" role="status">{{ notice }}</p>
    <form class="create" @submit.prevent="save">
      <label>供应商配置名称<input v-model="form.label" required maxlength="120"></label>
      <label>Base URL<input v-model="form.base_url" required type="url" placeholder="https://供应商域名/v1" maxlength="500"></label>
      <label>模型名称<input v-model="form.model" required maxlength="160"></label>
      <label>密钥环境变量名称<input v-model="form.secret_env" required pattern="[A-Z][A-Z0-9_]*_API_KEY" maxlength="128"></label>
      <label>计费币种<select v-model="form.currency"><option>CNY</option><option>USD</option></select></label>
      <label>输入单价（每百万 Token）<input v-model="form.input_per_million" inputmode="decimal" placeholder="未知，留空" pattern="[0-9]+(\.[0-9]{1,8})?"></label>
      <label>输出单价（每百万 Token）<input v-model="form.output_per_million" inputmode="decimal" placeholder="未知，留空" pattern="[0-9]+(\.[0-9]{1,8})?"></label>
      <label>输入 Token 安全上限<input v-model.number="form.input_token_limit" required type="number" min="256" max="2000000"></label>
      <label>输出 Token 安全上限<input v-model.number="form.output_token_limit" required type="number" min="128" max="32768"></label>
      <label>价格与计费上限核验来源<textarea v-model="form.price_source" maxlength="1000" placeholder="官方价目表、适用模型、核验日期及最大计费用量规则"></textarea></label>
      <label><input v-model="form.billing_verified" type="checkbox">已核实费率、输入上界及输出上限覆盖全部计费 Token</label>
      <label><input v-model="form.rejection_is_nonbillable" type="checkbox">供应商明确保证 400/401/403/404/422/429 拒绝不收费</label>
      <label>输出限制参数<select v-model="form.token_parameter"><option>max_completion_tokens</option><option>max_tokens</option></select></label>
      <label>结构化响应<select v-model="form.response_format"><option>json_schema</option><option>json_object</option></select></label>
      <label>网络读写超时（秒）<input v-model.number="form.timeout_seconds" required type="number" min="1" max="120"></label>
      <button :disabled="busy">保存禁用的真实配置</button>
    </form>
  </details>
</template>
