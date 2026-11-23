<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { customerApi, newId } from './api'
import { messageHtml, messageText } from './chatFormat'
import ApplianceCards from './ApplianceCards.vue'

const props = defineProps({ token: String, account: String, route: String, chatState: String })
const emit = defineEmits(['navigate', 'ready'])
const appliance = props.route.split('?')[0] === '/appliance'
const params = new URLSearchParams(props.route.split('?')[1])
const messages = ref([]), conversationId = ref(''), conversationMode = ref('AI')
const context = ref({}), version = ref(0), messageList = ref(null)
const cards = ref(null), draft = ref(''), error = ref(''), ready = ref(false)
const aiProcessingState = ref('idle'), aiProcessingMessage = ref(''), choiceSending = ref(false)
const serviceLabel = computed(() => conversationModeLabel(conversationMode.value))
let active = true, revision = 0

function navigate(to) { if (active) emit('navigate', to) }
async function enterAppliance(id) {
  try {
    const result = await customerApi.enterAppliance(props.token, id)
    navigate('/appliance?conversation=' + encodeURIComponent(result.conversation_id))
  } catch (cause) { error.value = cause.message }
}
async function refresh() {
  const stamp = ++revision
  const data = await customerApi.history(props.token, conversationId.value)
  if (!active || stamp !== revision) return
  if (data.service_scene !== (appliance ? 'APPLIANCE_SERVICE' : 'ECOMMERCE')) {
    throw Error('会话与当前入口不匹配')
  }
  const area = messageList.value
  const follow = !ready.value || !area || area.scrollHeight - area.clientHeight - area.scrollTop < 90
  conversationId.value = data.conversation_id
  conversationMode.value = data.conversation_mode
  context.value = data.service_context
  version.value = data.context_version
  const byId = new Map(data.messages.filter(m => m.conversation_id === data.conversation_id)
    .map(m => [m.message_id, m]))
  for (const message of messages.value) {
    if (message.delivery_status && !byId.has(message.message_id)) byId.set(message.message_id, message)
  }
  messages.value = [...byId.values()]
  const waiting = messages.value.at(-1)?.role === 'USER' && messages.value.at(-1)?.delivery_status !== 'failed' && data.conversation_mode === 'AI'
  aiProcessingMessage.value = waiting ? 'AI 正在处理你的问题' : ''
  aiProcessingState.value = waiting ? 'active' : 'idle'
  await nextTick()
  if (follow && area) area.scrollTop = area.scrollHeight
}
async function sync(event) {
  if (!conversationId.value || (event && event.conversation_id !== conversationId.value)) return
  try {
    await refresh()
    if (!event) await cards.value?.restore()
  } catch (cause) { if (active) error.value = cause.message }
}
async function sendPayload(type, content) {
  if (!ready.value || conversationMode.value === 'CLOSED') return
  const id = newId('msg')
  const message = {role: 'USER', type, content, conversation_id: conversationId.value,
    message_id: id, delivery_status: 'sending'}
  messages.value.push(message)
  if (conversationMode.value === 'AI') {
    aiProcessingState.value = 'active'
    aiProcessingMessage.value = 'AI 正在处理你的问题'
  }
  try {
    await customerApi.send(props.token, {conversation_id: conversationId.value, message_id: id, type, content})
    if (active) await refresh()
  } catch (cause) {
    if (!active) return
    const pending = messages.value.find(m => m.message_id === id)
    if (pending) pending.delivery_status = 'failed'
    error.value = cause.message
    await sync()
  }
}
function sendMessage() {
  const text = draft.value.trim()
  if (!ready.value || !text) return
  draft.value = ''
  sendPayload('text', {text})
}
onMounted(async () => {
  try {
    if (appliance && !params.get('conversation')) {
      const search = new URLSearchParams()
      if (params.has('ticket')) search.set('ticket_id', params.get('ticket'))
      if (params.has('draft')) search.set('new_repair', 'true')
      conversationId.value = (await customerApi.openAppliance(props.token, search)).conversation_id
    } else conversationId.value = params.get('conversation') || ''
    await refresh()
    if (active) { ready.value = true; emit('ready') }
  } catch (cause) { error.value = cause.message }
})
onBeforeUnmount(() => { active = false; revision++ })
defineExpose({sync, sendPayload})
function conversationModeLabel(mode) {
  return {
    AI: 'AI 客服',
    BOT: 'AI 客服',
    QUEUED: '等待人工',
    HUMAN: '人工服务中',
    CLOSED: '已结束',
  }[mode] || mode
}

function actionHref(message) {
  return message.content?.page_action?.href
}

function messageChoices(message) {
  const choices = message.content?.choices
  if (!Array.isArray(choices)) return []
  return choices.filter((choice) => (
    ['order', 'product'].includes(choice?.object_type)
    && typeof choice?.object_id === 'string'
    && typeof choice?.label === 'string'
  ))
}

async function selectChoice(choice) {
  if (choiceSending.value) return
  choiceSending.value = true
  try {
    const content = {
      object_type: choice.object_type,
      object_id: choice.object_id,
    }
    if (typeof choice.query_text === 'string') {
      content.query_text = choice.query_text
    }
    await sendPayload('object', content)
  } finally {
    choiceSending.value = false
  }
}


</script>
<template>
        <section class="chat-layout" :data-conversation="conversationId" :data-scene="appliance ? 'appliance' : 'commerce'">
          <div class="chat-workspace">
            <section class="chat-intro">
              <div v-if="appliance"><h1>家电售后咨询</h1></div>
              <div v-else><p class="eyebrow">AI CUSTOMER SERVICE</p><h1>有问题，直接问</h1><p>我会查询订单和规则，说明结果，并带你到正确的业务页面。</p></div>
              <div class="chat-status">
                <span :class="['service-mode', conversationMode.toLowerCase()]">{{ serviceLabel }}</span>
                <span :class="['connection', chatState]">{{ chatState === 'connected' ? '在线' : '连接中' }}</span>
              </div>
            </section>
            <p v-if="error" role="alert">{{ error }}</p>
            <ApplianceCards v-if="appliance && ready" ref="cards" :token="token" :account="account"
              :cid="conversationId" :ctx="context" :mode="conversationMode" :version="version"
              @navigate="navigate" @send="sendPayload" />
            <section ref="messageList" class="messages" aria-label="对话消息" aria-live="polite">
              <div v-if="!messages.length" class="empty-chat">
                <strong v-if="appliance">请描述故障现象，例如「洗衣机 E3」。</strong>
                <template v-else><strong>可以试试</strong>
                <button @click="draft = '我的订单什么时候发货？'; sendMessage()">我的订单什么时候发货？</button>
                <button @click="draft = '我想取消订单'; sendMessage()">我想取消订单</button>
                <button @click="draft = '我想了解平台售后规则'; sendMessage()">我想了解平台售后规则</button></template>
              </div>
              <article v-for="(message, index) in messages" :key="message.message_id" :data-message-id="message.message_id" :class="['message', message.role.toLowerCase()]">
                <span class="avatar">{{ message.role === 'USER' ? '我' : message.role === 'HUMAN' ? '人' : 'AI' }}</span>
                <div class="bubble">
                  <div v-if="message.role === 'USER'" class="message-text">{{ messageText(message) }}</div>
                  <div v-else class="message-text markdown-body" v-html="messageHtml(message)"></div>
                  <template v-if="appliance && message.role === 'AI'">
                    <p v-for="c in message.content.citations" :key="c.id">依据：{{ c.file_name }} · {{ c.model_code }} · 第 {{ c.page_no }} 页 · {{ c.section }}</p>
                    <div v-if="message.content.step">
                      <p>{{ message.content.step.text }}</p>
                      <button v-for="(label,k) in {resolved:'已恢复',unresolved:'未恢复'}" :key="k"
                        :disabled="conversationMode !== 'AI' || context.pending_step?.id !== message.content.step.id || message.message_id !== messages.at(-1)?.message_id"
                        @click="sendPayload('step_feedback',{step_id:message.content.step.id,outcome:k,device_id:context.device.device_id,context_version:version})">{{ label }}</button>
                    </div>
                    <button v-for="d in (message.content.choices || []).filter(c => c.device_id)" :key="d.device_id"
                      :disabled="conversationMode !== 'AI' || message.message_id !== messages.at(-1)?.message_id"
                      @click="sendPayload('device_choice',{device_id:d.device_id})">{{ d.display_name }} · {{ d.serial_no }}</button>
                    <p v-if="message.content.warranty">{{ message.content.warranty.notice }} · {{ message.content.warranty.months }} 个月 · 签收 {{ message.content.warranty.signed_on || '待核验' }} · 首个过保日 {{ message.content.warranty.exclusive_end || '待核验' }}</p>
                    <p v-for="t in message.content.tickets" :key="t.ticket_id">{{ t.ticket_id }} · {{ t.device.display_name }} · {{ t.description }} · {{ t.created_at }} · 待受理</p>
                    <button v-if="message.content.page_action?.action_code === 'OPEN_REPAIR_PREVIEW'"
                      :disabled="conversationMode !== 'AI' || message.message_id !== messages.at(-1)?.message_id || context.device?.device_id !== message.content.page_action.device_id"
                      @click="cards?.preview()">打开维修预览</button>
                  </template>
                  <small v-if="message.delivery_status === 'sending'" class="delivery-state">发送中</small>
                  <small v-else-if="message.delivery_status === 'failed'" class="delivery-state failed">发送失败</small>
                  <div v-if="messageChoices(message).length" class="choice-list" aria-label="请选择咨询对象">
                    <button
                      v-for="choice in messageChoices(message)"
                      :key="`${choice.object_type}:${choice.object_id}`"
                      :disabled="choiceSending"
                      @click="selectChoice(choice)"
                    >
                      <span><strong>{{ choice.label }}</strong><small>{{ choice.description }}</small></span>
                      <b>→</b>
                    </button>
                  </div>
                  <button v-if="message.role === 'AI' && message.content?.page_action?.source_id" class="action-card" @click="enterAppliance(message.content.page_action.source_id)">进入家电售后</button>
                  <button v-if="actionHref(message)" class="action-card" @click="navigate(actionHref(message))">
                    <span><strong>{{ message.content.page_action.label }}</strong><small>{{ message.content.page_action.description }}</small></span><b>→</b>
                  </button>
                </div>
              </article>
              <article
                v-if="aiProcessingMessage"
                :class="['message', 'ai-processing', aiProcessingState]"
                role="status"
                aria-live="polite"
              >
                <span class="avatar">AI</span>
                <div class="bubble processing-bubble">
                  <span v-if="aiProcessingState === 'active'" class="processing-dots" aria-hidden="true">
                    <i></i><i></i><i></i>
                  </span>
                  <span v-else class="processing-failed-mark" aria-hidden="true">!</span>
                  <span>{{ aiProcessingMessage }}</span>
                </div>
              </article>
            </section>
            <form class="composer" @submit.prevent="sendMessage">
              <textarea v-model="draft" rows="2" aria-label="输入客服问题" placeholder="描述你的问题；业务操作会在对应页面确认" @keydown.enter.exact.prevent="sendMessage" />
              <button :disabled="!ready || !draft.trim() || conversationMode === 'CLOSED'">发送</button>
            </form>
          </div>
        </section>
</template>

<style scoped>
.chat-workspace { display:flex; flex-direction:column; height:100%; min-height:0 }
.messages { flex:1; min-height:12rem }
</style>
