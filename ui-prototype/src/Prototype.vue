<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import HandoffDetail from './HandoffDetail.vue'
import ServiceCards from './ServiceCards.vue'
import { initial, devices, storageKey, serviceDate, warranty, consult, selectDevice, feedback, openPreview, confirmPreview, message, formatTime } from './demo.js'
import './prototype.css'

function load() {
  try { return JSON.parse(localStorage.getItem(storageKey)) || initial() } catch { return initial() }
}
const state = ref(load())
const route = () => location.pathname.split('/')[2] || 'chat'
const page = ref(route())
const input = ref('')
const modal = ref('')
const dialog = ref(null)
const stream = ref(null)
const device = computed(() => devices.find(d => d.id === state.value.deviceId))
const ticket = computed(() => state.value.tickets.find(t => t.deviceId === state.value.deviceId))
const nav = [['chat','售后咨询'],['tickets','我的维修工单'],['staff','客服工作台']]
const title = computed(() => ({chat:'智能家电售后助手',tickets:'我的维修工单',staff:'人工接待工作台'})[page.value])
watch(state, s => localStorage.setItem(storageKey, JSON.stringify(s)), { deep: true })
function sync(e) { if (e.key === storageKey && e.newValue && JSON.stringify(state.value) !== e.newValue) state.value = JSON.parse(e.newValue) }
function back() { page.value = route(); close() }
onMounted(() => { document.title = '家电售后服务 · DEMO'; window.addEventListener('storage',sync); window.addEventListener('popstate',back) })
onUnmounted(() => { window.removeEventListener('storage',sync); window.removeEventListener('popstate',back) })
watch(() => state.value.messages.length, async () => { await nextTick(); if (stream.value) stream.value.scrollTop = stream.value.scrollHeight })
function go(p) { if (page.value !== p) history.pushState({},'', '/prototype/' + p); page.value = p; close() }
async function show(kind) { modal.value = kind; await nextTick(); dialog.value?.showModal() }
function close() { dialog.value?.close(); modal.value = '' }
function send(text) { consult(state.value,text); input.value = ''; if (state.value.phase === 'choose') show('devices') }
function preview() { const result = openPreview(state.value); if (result === 'existing') go('tickets'); else if (result) show('preview') }
function reset() { state.value = initial(); input.value=''; go('chat') }
function accept() { state.value.handoff.status='ACTIVE'; message(state.value,'客服','您好，已接入本次售后咨询。') }
</script>
<template>
<main class="proto">
  <header class="proto-top"><div class="brand"><span class="brand-mark" aria-hidden="true">∿</span> 家电服务中心 <span class="pill">DEMO</span></div><button @click="show('reset')">重置演示</button></header>
  <div class="proto-nav" aria-label="演示页面"><button v-for="[key,label] in nav" :key="key" :class="{ selected: page === key }" @click="go(key)">{{ label }}</button></div>
  <div class="proto-title"><h1>{{ title }}</h1><span class="date">演示业务日 · {{ serviceDate }}</span></div>
  <div v-if="page === 'chat'" class="proto-columns">
    <section class="proto-panel chat-room"><div class="section-head"><h2>服务对话</h2><span class="pill">{{ state.handoff ? (state.handoff.status === 'ACTIVE' ? '人工接待中' : '等待人工接入') : '智能助手' }}</span></div>
      <div ref="stream" class="transcript" role="log">
        <div v-if="!state.messages.length" class="welcome"><span class="signal" aria-hidden="true">∿</span><h2>哪台家电需要帮助？</h2><p>描述故障现象，或从下面的问题开始。</p><div class="actions"><button @click="send('设备显示 E3，怎么处理？')">设备显示 E3</button><button @click="send('设备正在冒烟')">设备正在冒烟</button></div></div>
        <article v-for="m in state.messages" :key="m.id" :class="['bubble',{ mine: m.role === '用户' }]"><small>{{ m.role }}</small><p>{{ m.text }}</p></article>
        <ServiceCards v-if="state.phase === 'steps'" kind="step" :device="device" :session="state" @feedback="feedback(state,$event)" />
        <button v-if="state.phase === 'choose'" @click="show('devices')">选择具体设备</button>
        <button v-if="state.phase === 'repair'" class="accent" @click="preview">{{ ticket ? '查看已有工单' : '打开维修工单预览' }}</button>
      </div>
      <form class="compose" @submit.prevent="send(input)"><input v-model="input" aria-label="咨询内容" placeholder="输入故障现象或故障码…" maxlength="500"><button class="accent" :disabled="!input.trim()">发送 ↑</button></form>
    </section>
    <aside class="proto-panel side"><div class="section-head"><h2>当前设备</h2></div><div class="block">
      <div class="equipment" :class="{air:device?.id==='a1'}" aria-hidden="true"><i></i></div>
      <h2>{{ device?.name || '尚未选择设备' }}</h2><p>{{ device ? device.model + ' · ' + device.sn : '咨询后可从本人订单中选择设备。' }}</p>
      <template v-if="device"><dl><dt>保修状态</dt><dd>{{ warranty(device).status }}</dd><dt>整机期限</dt><dd>{{ device.months }} 个月</dd></dl></template>
      <div class="side-actions" v-if="!state.handoff && state.messages.length"><button @click="show('devices')">{{ device ? '更换设备' : '选择设备' }}</button><button v-if="device" @click="preview">{{ ticket ? '查看已有工单' : '维修预览' }}</button></div>
      <hr><h3>人工服务</h3><p>{{ state.handoff ? state.handoff.reason : '需要客服核验时，可转接当前对话。' }}</p>
      <button @click="state.handoff ? go('staff') : send('转人工')">{{ state.handoff ? '查看客服接入详情 →' : '转人工' }}</button>
    </div></aside>
  </div>
  <section v-else-if="page === 'tickets'" class="proto-panel"><div class="section-head"><h2>本人维修记录</h2><span class="pill">{{ state.tickets.length }} 张</span></div>
    <div v-if="!state.tickets.length" class="empty"><h2>暂无维修工单</h2><p>在咨询中核对维修预览并确认后，可在这里查看工单。</p><button @click="go('chat')">返回售后咨询</button></div>
    <article v-for="t in state.tickets" :key="t.id" class="block ticket"><span class="pill">{{ t.status }}</span><h3>{{ t.id }}</h3><p>{{ devices.find(d=>d.id===t.deviceId).name }} · {{ devices.find(d=>d.id===t.deviceId).sn }}</p><p>{{ t.description }}</p><small>创建时间 · {{ formatTime(t.at) }}</small></article>
  </section>
  <HandoffDetail v-else :session="state" :device="device" :ticket="ticket" :format-time="formatTime" @accept="accept" @reply="message(state,'客服',$event)" @example="send('设备显示 E3，而且正在冒烟')" />
  <dialog ref="dialog" aria-labelledby="modal-title" @close="modal=''">
    <div class="section-head"><h2 id="modal-title">{{ {devices:'选择具体设备',preview:'维修工单预览',reset:'重置本次演示？'}[modal] }}</h2><button aria-label="关闭" @click="close">×</button></div>
    <div class="block"><template v-if="modal === 'reset'"><p>将清除本浏览器中的 DEMO 消息、工单和交接记录。</p><div class="actions"><button @click="close">取消</button><button class="accent" @click="reset">重置演示</button></div></template>
    <template v-else><p v-if="modal==='devices'">请对照机身序列号。同型号设备可分别报修。</p><ServiceCards :kind="modal" :device="device" :session="state" @select="selectDevice(state,$event); close()" @confirm="confirmPreview(state,$event); go('tickets')" @close="close" /></template></div>
  </dialog>
</main>
</template>
