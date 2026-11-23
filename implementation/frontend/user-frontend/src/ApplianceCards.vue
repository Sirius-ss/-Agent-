<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { apiFetch, ECOMMERCE_SERVICE_URL } from './api'

const props = defineProps({token:String, account:String, cid:String, ctx:Object, mode:String, version:Number})
const emit = defineEmits(['send','navigate'])
const devices = ref([]), tickets = ref([]), showTickets = ref(false)
const draft = ref(null), editing = ref(false), description = ref(''), busy = ref(false), error = ref('')
const existingTicket = ref(null)
const previewFeedback = ref(null)
const selected = computed(() => props.ctx.device)
const storageKey = computed(() => 'repair-preview/' + props.account + '/' + props.cid)
let active = true, sequence = 0, expiry
function shop(path, body) {
  return apiFetch(ECOMMERCE_SERVICE_URL, '/api/v1/' + path, props.token, body ? {
    method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)
  } : {})
}
function close() {
  sequence++
  clearTimeout(expiry)
  draft.value = null
  existingTicket.value = null
  editing.value = false
  sessionStorage.removeItem(storageKey.value)
}
function show(data) {
  clearTimeout(expiry)
  draft.value = data
  sessionStorage.setItem(storageKey.value, JSON.stringify({id:data.preview_id, version:props.version}))
  expiry = setTimeout(close, Math.max(0, Date.parse(data.expires_at) - Date.now()))
}
async function restore() {
  const stamp = ++sequence
  try {
    const rows = await shop('repair-tickets')
    if (!active || stamp !== sequence) return
    tickets.value = rows.data
    const saved = JSON.parse(sessionStorage.getItem(storageKey.value) || 'null')
    if (!saved || saved.version !== props.version || props.mode !== 'AI') return close()
    const current = await shop('repair-previews/' + encodeURIComponent(saved.id))
    if (!active || stamp !== sequence) return
    if (current.data.device.device_id === selected.value?.device_id) show(current.data)
    else close()
  } catch (cause) {
    if (active && stamp === sequence) {
      if (cause.status === 404 || cause.status === 409) close()
      error.value = cause.message
    }
  }
}
function ticket(id) { emit('navigate', '/appliance?ticket=' + encodeURIComponent(id)) }
async function preview(replace=false) {
  if (busy.value) return
  error.value = ''
  if (!selected.value || !props.ctx.description?.trim() || props.mode !== 'AI') {
    error.value = '请在 AI 咨询中选择设备并描述故障后，再打开维修预览。'
    return
  }
  if (draft.value && !replace) {
    previewFeedback.value?.scrollIntoView({ block: 'nearest' })
    return
  }
  existingTicket.value = null
  busy.value = true
  const version = props.version
  sequence++
  error.value = ''
  try {
    const result = await shop('repair-previews', {device_id:selected.value.device_id,
      description:replace ? description.value.trim() : props.ctx.description,
      ...(replace ? {replaces_preview_id:draft.value.preview_id} : {})})
    if (!active || props.version !== version || props.mode !== 'AI') return
    if (result.code === 'EXISTING_TICKET') {
      close()
      existingTicket.value = result.data
    }
    else { show(result.data); editing.value = false }
    await nextTick()
    previewFeedback.value?.scrollIntoView({ block: 'nearest' })
  } catch (cause) { error.value = cause.message }
  finally { busy.value = false }
}
async function confirm() {
  if (!draft.value || busy.value || props.mode !== 'AI') return
  busy.value = true
  try {
    const result = await shop('repair-previews/' + draft.value.preview_id + '/confirm', {confirmed:true})
    if (active) { close(); await restore(); ticket(result.data.ticket_id) }
  } catch (cause) { error.value = cause.message; await restore() }
  finally { busy.value = false }
}
async function toggleTickets() {
  showTickets.value = !showTickets.value
  if (showTickets.value) await restore()
}
onMounted(async () => {
  try { devices.value = (await shop('devices')).data; await restore() }
  catch (cause) { error.value = cause.message }
})
watch([() => props.version, () => props.mode], close)
onBeforeUnmount(() => { active = false; clearTimeout(expiry) })
defineExpose({restore, preview})
</script>
<template>
  <section class="appliance-tools" aria-label="家电服务">
    <details><summary>本人设备 · {{ selected?.serial_no || '请选择' }}</summary>
      <button v-for="d in devices" :key="d.device_id" :disabled="mode !== 'AI'"
        @click="emit('send','device_choice',{device_id:d.device_id})">{{ d.display_name }} · {{ d.serial_no }}</button>
    </details>
    <button @click="toggleTickets">我的维修工单 · {{ tickets.length }}</button>
    <button @click="emit('navigate','/appliance?draft=1')">创建新的维修工单</button>
    <button v-if="mode === 'AI'" @click="emit('send','request_handoff',{text:'转人工'})">转人工</button>
    <button v-if="mode === 'AI' && selected && ctx.description && !draft" :disabled="busy" @click="preview()">维修申请预览</button>
    <div v-if="showTickets" class="card">
      <p v-if="!tickets.length">暂无维修工单</p>
      <button v-for="t in tickets" :key="t.ticket_id" @click="ticket(t.ticket_id)">
        {{ t.ticket_id }} · {{ t.device.display_name }} · {{ t.description }} · {{ t.created_at }} · 待受理
      </button>
    </div>
    <section v-if="existingTicket" ref="previewFeedback" class="card">
      <strong role="status">该设备已有维修工单</strong>
      <p>{{ existingTicket.device.display_name }} · {{ existingTicket.ticket_id }}</p>
      <button @click="ticket(existingTicket.ticket_id)">查看已有工单</button>
      <button @click="close">关闭</button>
    </section>
    <section v-if="draft && mode === 'AI'" ref="previewFeedback" class="card" aria-label="维修工单预览">
      <strong>维修工单预览</strong><p>{{ draft.device.display_name }} · {{ draft.device.serial_no }}</p>
      <textarea v-if="editing" v-model="description" maxlength="500" aria-label="工单摘要" />
      <p v-else>{{ draft.description }}</p><p>{{ draft.notice }} · {{ draft.warranty.months }} 个月</p>
      <button v-if="editing" :disabled="busy || !description.trim()" @click="preview(true)">更新预览</button>
      <template v-else><button :disabled="busy" @click="confirm">确认提交维修申请</button>
        <button @click="editing=true;description=draft.description">编辑工单摘要</button></template>
      <button :disabled="busy" @click="close">关闭</button>
    </section>
    <p v-if="error" role="alert">{{ error }}</p>
  </section>
</template>
<style scoped>
.appliance-tools {display:flex;align-items:flex-start;flex-wrap:wrap;gap:.5rem;padding:.6rem 0}
.card {width:100%;max-height:32vh;overflow:auto;border:1px solid var(--line);padding:.65rem}
summary {cursor:pointer}
</style>
