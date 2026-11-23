<script setup>
import ChatWorkspace from './ChatWorkspace.vue'
import { messageText } from './chatFormat.js'
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { commerceApi, createRealtimeConnection, customerApi, listDemoUsers, login, newId } from './api'

const workspace = ref(null)
let loginVersion = 0

const mallProductIds = new Set(['W-DEMO', 'A-DEMO', 'W-DEMO-PLUS', 'A-DEMO-PRO'])
const session = reactive({ token: '', user: null })
const demoUsers = ref([])
const selectedUser = ref(localStorage.getItem('customer_id') || 'user_001')
const route = ref(`${location.pathname}${location.search}`)
const loading = ref(false)
const error = ref('')
const notice = ref('')
const orders = ref([])
const products = ref([])
const order = ref(null)
const logistics = ref(null)
const afterSales = ref([])
const historyMessages = ref([])
const expandedConversationIds = ref(new Set())
const conversationId = ref(null)
const chatState = ref('closed')
const pendingConsult = ref(null)
const afterSalesPanel = ref(null)
const form = reactive({ address: '', kind: 'refund', reason: '' })
let realtime

const path = computed(() => route.value.split('?')[0])
const isChat = computed(() => ['/', '/chat', '/appliance'].includes(path.value))
const query = computed(() => new URLSearchParams(route.value.split('?')[1] || ''))
const orderMatch = computed(() => path.value.match(/^\/me\/orders\/([^/]+)(?:\/(cancel|address|after-sale))?$/))
const orderId = computed(() => orderMatch.value?.[1] || '')
const operation = computed(() => orderMatch.value?.[2] || '')
const selectedProfile = computed(() => demoUsers.value.find((user) => user.id === selectedUser.value))
const canCancel = computed(() => ['paid', 'pending_shipment'].includes(order.value?.status))
const canEditAddress = computed(() => ['paid', 'pending_shipment'].includes(order.value?.status))
const canApplyAfterSale = computed(() => !['cancelled', 'refunded'].includes(order.value?.status))
const historyGroups = computed(() => {
  const groups = new Map()
  for (const message of historyMessages.value) {
    if (!groups.has(message.conversation_id)) {
      groups.set(message.conversation_id, {
        id: message.conversation_id,
        messages: []
      })
    }
    groups.get(message.conversation_id).messages.push(message)
  }
  return [...groups.values()]
    .map((group) => ({
      ...group,
      title: messageText(group.messages[0]),
      preview: messageText(group.messages[group.messages.length - 1])
    }))
    .reverse()
})
const pageTitle = computed(() => {
  if (path.value === '/appliance') return '家电售后'
  if (path.value === '/mall') return '商城'
  if (path.value === '/chat' || path.value === '/') return '智能客服'
  if (path.value === '/history') return '历史会话'
  if (path.value === '/me') return '我的'
  if (operation.value === 'cancel') return '取消订单'
  if (operation.value === 'address') return '修改收货地址'
  if (operation.value === 'after-sale') return '申请售后'
  return '订单详情'
})

function navigate(to, { keepNotice = false } = {}) {
  if (!keepNotice) notice.value = ''
  history.pushState({}, '', to)
  route.value = `${location.pathname}${location.search}`
}

function unwrap(result) {
  if (!result.success) throw new Error(result.message || '请求失败')
  return result.data
}

function unwrapAfterSales(result) {
  if (result.code === 'AFTER_SALE_NOT_FOUND') return []
  return unwrap(result)
}

function toggleHistoryGroup(conversationId) {
  const next = new Set(expandedConversationIds.value)
  if (next.has(conversationId)) next.delete(conversationId)
  else next.add(conversationId)
  expandedConversationIds.value = next
}

function sendPendingConsult() {
  if (!pendingConsult.value || path.value !== '/chat' || !workspace.value) return
  const {objectType, objectId} = pendingConsult.value
  pendingConsult.value = null
  workspace.value.sendPayload('object', {object_type: objectType, object_id: objectId})
}

async function establishSession() {
  error.value = ''
  loading.value = true
  const version = ++loginVersion
  realtime?.close()
  session.token = ''
  historyMessages.value = []
  orders.value = []
  try {
    const result = await login(selectedUser.value)
    if (version !== loginVersion) return
    session.token = result.access_token
    session.user = result
    localStorage.setItem('customer_token', session.token)
    localStorage.setItem('customer_id', selectedUser.value)
    realtime = createRealtimeConnection(session.token, {
      onState: (state) => { if (version === loginVersion) chatState.value = state },
      onEvent: event => {
        if (version !== loginVersion) return
        workspace.value?.sync(event)
        if (path.value === '/history') loadHistory().catch(cause => { error.value = cause.message })
      },
      onConnected: () => { if (version === loginVersion) workspace.value?.sync() },
    })
    await loadPage()
  } catch (cause) {
    if (version === loginVersion) error.value = cause.message
  } finally {
    if (version === loginVersion) loading.value = false
  }
}

async function loadHistory() {
  if (!session.token) return
  const token = session.token
  const data = await customerApi.archive(token)
  if (token !== session.token || path.value !== '/history') return
  conversationId.value = data.conversation_id
  historyMessages.value = data.messages
  if (!expandedConversationIds.value.size && conversationId.value) {
    expandedConversationIds.value = new Set([conversationId.value])
  }
  await nextTick()
}

async function loadOrder() {
  const [orderResult, afterSaleResult] = await Promise.all([
    commerceApi.order(session.token, orderId.value),
    commerceApi.afterSales(session.token, orderId.value),
  ])
  order.value = unwrap(orderResult)
  afterSales.value = unwrapAfterSales(afterSaleResult)
  form.address = order.value.address || ''
  logistics.value = null
  if (!operation.value) {
    try { logistics.value = unwrap(await commerceApi.logistics(session.token, orderId.value)) } catch { /* no logistics yet */ }
    if (query.value.get('section') === 'after-sales') {
      await nextTick()
      afterSalesPanel.value?.scrollIntoView({ behavior: 'smooth', block: 'center' })
    }
  }
}

async function loadPage() {
  if (!session.token) return
  error.value = ''
  loading.value = true
  try {
    if (path.value === '/mall') {
      const catalog = unwrap(await commerceApi.products(session.token))
      products.value = catalog.filter((product) => mallProductIds.has(product.id))
    }
    else if (isChat.value) return
    else if (path.value === '/history') await loadHistory()
    else if (path.value === '/me') orders.value = unwrap(await commerceApi.orders(session.token)).filter(order => order.items.some(item => mallProductIds.has(item.product_id)))
    else if (orderId.value) await loadOrder()
    else navigate('/mall')
  } catch (cause) {
    error.value = cause.message
  } finally {
    loading.value = false
  }
}

function consultObject(objectType, objectId) {
  pendingConsult.value = { objectType, objectId }
  navigate('/chat')
}

async function submitCancel() {
  if (!confirm(`确认取消订单 ${orderId.value}？此操作会立即生效。`)) return
  await runWrite(async () => unwrap(await commerceApi.cancel(session.token, orderId.value)), '订单已取消', `/me/orders/${orderId.value}`)
}

async function submitAddress() {
  await runWrite(async () => unwrap(await commerceApi.updateAddress(session.token, orderId.value, form.address)), '收货地址已更新', `/me/orders/${orderId.value}`)
}

async function submitAfterSale() {
  await runWrite(
    async () => unwrap(await commerceApi.createAfterSale(session.token, orderId.value, { kind: form.kind, reason: form.reason })),
    '售后申请已提交',
    `/me/orders/${orderId.value}?section=after-sales`,
  )
}

async function runWrite(action, successMessage, target) {
  loading.value = true
  error.value = ''
  try {
    await action()
    notice.value = successMessage
    navigate(target, { keepNotice: true })
  } catch (cause) {
    error.value = cause.message
  } finally {
    loading.value = false
  }
}

function afterSaleKind(kind) {
  return { refund: '仅退款', return: '退货退款', exchange: '换货' }[kind] || kind
}

function afterSaleStatus(status) {
  return { pending: '待处理', approved: '已通过', processing: '处理中', completed: '已完成', rejected: '未通过' }[status] || status
}

function logisticsStatus(status) {
  return { pending: '待揽收', picked_up: '已揽收', in_transit: '运输中', delivered: '已签收', exception: '物流异常' }[status] || status
}

onMounted(async () => {
  window.addEventListener('popstate', () => { route.value = `${location.pathname}${location.search}` })
  demoUsers.value = await listDemoUsers().catch(() => [])
  await establishSession()
})
onBeforeUnmount(() => realtime?.close())
watch(route, loadPage)
</script>

<template>
  <div class="app-shell">
    <header class="topbar">
      <button class="brand" @click="navigate('/mall')"><span>小满</span> 商城</button>
      <nav aria-label="主导航"><button :class="{active:path==='/appliance'}" @click="navigate('/appliance')">家电售后</button>
        <button :class="{ active: path === '/mall' }" :aria-current="path === '/mall' ? 'page' : undefined" @click="navigate('/mall')">商城</button>
        <button :class="{ active: path === '/chat' || path === '/' }" :aria-current="path === '/chat' || path === '/' ? 'page' : undefined" @click="navigate('/chat')">客服</button>
        <button :class="{ active: path === '/history' }" :aria-current="path === '/history' ? 'page' : undefined" @click="navigate('/history')">历史</button>
        <button :class="{ active: path.startsWith('/me') }" :aria-current="path.startsWith('/me') ? 'page' : undefined" @click="navigate('/me')">我的</button>
      </nav>
      <div class="account">
        <select v-model="selectedUser" aria-label="切换体验账号" @change="establishSession">
          <option v-for="user in demoUsers" :key="user.id" :value="user.id">{{ user.name }}</option>
        </select>
      </div>
    </header>

    <main :class="['page', { 'chat-page': isChat }]">
      <div v-if="error" class="alert error" role="alert">{{ error }} <button aria-label="关闭错误提示" @click="error = ''">×</button></div>
      <div v-if="notice" class="alert success" role="status">{{ notice }} <button aria-label="关闭成功提示" @click="notice = ''">×</button></div>

      <template v-if="path === '/mall'">
        <section class="mall-hero">
          <div>
            <p class="eyebrow">XIAOMAN SELECT</p>
            <h1>挑一件，问清楚</h1>
            <p>这里仅展示商品的必要信息。想了解规格、功能或适用场景，直接带着商品去问客服。</p>
          </div>
          <span>{{ products.length }} 件精选</span>
        </section>
        <section class="mall-grid" aria-label="精选商品">
          <article v-for="(item, index) in products" :key="item.id" class="mall-card">
            <div class="mall-art" :data-index="String(index + 1).padStart(2, '0')">
              <img :src="item.id.startsWith('W-') ? '/demo-washer.svg' : '/demo-ac.svg'" :alt="item.name" style="width:100%;height:100%;object-fit:contain">
            </div>
            <div class="mall-card-body">
              <p>{{ item.category }}</p>
              <h2>{{ item.name }}</h2>
              <div class="mall-card-footer">
                <strong>¥{{ item.price.toFixed(2) }}</strong>
                <button @click="consultObject('product', item.id)">咨询商品 <span>→</span></button>
              </div>
            </div>
          </article>
          <div v-if="!products.length" class="empty-state"><h2>暂无商品</h2><p>精选商品正在准备中。</p></div>
        </section>
      </template>

      <ChatWorkspace v-else-if="isChat && session.token" ref="workspace"
        :key="session.token + route" :token="session.token" :account="selectedUser" :route="route"
        :chat-state="chatState" @navigate="navigate" @ready="sendPendingConsult" />

      <template v-else-if="path === '/history'">
        <section class="history-hero">
          <div>
            <p class="eyebrow">CONVERSATION ARCHIVE</p>
            <h1>历史会话</h1>
            <p>按照会话开始时间整理，展开即可回看当时的完整咨询记录。</p>
          </div>
          <span>{{ historyGroups.length }} 次会话</span>
        </section>

        <section class="history-list" aria-label="历史会话列表">
          <article
            v-for="(group, index) in historyGroups"
            :key="group.id"
            :class="['history-group', { expanded: expandedConversationIds.has(group.id) }]"
          >
            <button
              class="history-group-head"
              :aria-expanded="expandedConversationIds.has(group.id)"
              @click="toggleHistoryGroup(group.id)"
            >
              <span class="history-index">{{ String(index + 1).padStart(2, '0') }}</span>
              <span class="history-summary">
                <span>
                  <strong>{{ group.title }}</strong>
                  <b v-if="group.id === conversationId">当前会话</b>
                </span>
                <small>{{ group.preview }}</small>
              </span>
              <span class="history-count">{{ group.messages.length }} 条 <b>⌄</b></span>
            </button>

            <div v-if="expandedConversationIds.has(group.id)" class="history-transcript">
              <button @click="navigate((group.messages[0].service_scene === 'APPLIANCE_SERVICE' ? '/appliance' : '/chat') + '?conversation=' + encodeURIComponent(group.id))">打开此会话</button>
              <article
                v-for="(message, msgIndex) in group.messages"
                :key="msgIndex"
                :class="['history-message', message.role.toLowerCase()]"
              >
                <span>{{ message.role === 'USER' ? '我' : message.role === 'HUMAN' ? '人工客服' : 'AI 客服' }}</span>
                <div>
                  <p>{{ messageText(message) }}</p>
                </div>
              </article>
            </div>
          </article>

          <div v-if="!historyGroups.length" class="empty-state">
            <h2>还没有历史会话</h2>
            <p>完成第一次咨询后，会话记录会显示在这里。</p>
          </div>
        </section>
      </template>

      <template v-else-if="path === '/me'">
        <section class="profile-card">
          <div class="profile-avatar">{{ session.user?.display_name?.slice(0, 1) || '我' }}</div>
          <div><p class="eyebrow">MEMBER CENTER</p><h1>{{ session.user?.display_name || '我的' }}</h1><p>{{ selectedProfile?.membership || '普通会员' }} · {{ selectedUser }}</p></div>
        </section>
        <header class="section-header"><div><h2>我的订单</h2><p>查看家电购买记录、发货状态和订单详情。</p></div><span>{{ orders.length }} 笔</span></header>
        <section class="card-list">
          <article v-for="item in orders" :key="item.id" class="order-card">
            <div class="order-meta"><span>{{ item.id }}</span><b class="status-pill">订单状态 · {{ item.status_label || item.status }}</b></div>
            <div style="display:flex; align-items:center; gap:12px; flex-wrap:wrap">
              <img v-for="entry in item.items.filter(entry => mallProductIds.has(entry.product_id))"
                :key="entry.product_id" :src="entry.product_id.startsWith('W-') ? '/demo-washer.svg' : '/demo-ac.svg'"
                :alt="entry.product_name" width="92" height="64" style="object-fit:contain">
              <h3>{{ item.items.map((entry) => `${entry.product_name} · ${entry.product_id}`).join('、') }}</h3>
            </div>
            <div class="order-footer"><span>{{ new Date(item.created_at).toLocaleDateString() }}</span><strong>¥{{ item.total_amount.toFixed(2) }}</strong></div>
            <div class="order-actions">
              <button class="order-detail" @click="navigate(`/me/orders/${item.id}`)">订单详情</button>
              <button class="consult-order" @click="consultObject('order', item.id)">咨询订单 <span>→</span></button>
            </div>
          </article>
          <div v-if="!orders.length" class="empty-state"><h2>暂无订单</h2><p>当前账号还没有订单记录。</p></div>
        </section>
      </template>

      <template v-else-if="order">
        <header class="page-header"><div><button class="back" @click="navigate(operation ? `/me/orders/${order.id}` : '/me')">← 返回</button><p class="eyebrow">{{ order.id }}</p><h1>{{ pageTitle }}</h1></div><span class="status-pill">{{ order.status_label }}</span></header>

        <section v-if="!operation" class="detail-grid">
          <article class="panel wide"><h2>商品信息</h2><div v-for="item in order.items" :key="item.product_id" class="line-item"><span><strong>{{ item.product_name }}</strong><small>数量 ×{{ item.quantity }}</small></span><b>¥{{ (item.unit_price * item.quantity).toFixed(2) }}</b></div><div class="total"><span>实付款</span><strong>¥{{ order.total_amount.toFixed(2) }}</strong></div></article>
          <article class="panel"><h2>收货地址</h2><p>{{ order.address }}</p><button v-if="canEditAddress" class="text-button" @click="navigate(`/me/orders/${order.id}/address`)">修改地址 →</button><small v-else>当前订单状态不可修改</small></article>
          <article class="panel"><h2>物流信息</h2><template v-if="logistics"><strong>{{ logisticsStatus(logistics.status) }}</strong><p>{{ logistics.company }} · {{ logistics.tracking_number }}</p><small>{{ logistics.latest_event }}</small></template><p v-else>暂时没有物流信息</p></article>
          <article ref="afterSalesPanel" class="panel wide after-sales-panel"><div class="panel-title"><h2>售后记录</h2><button v-if="canApplyAfterSale" @click="navigate(`/me/orders/${order.id}/after-sale`)">申请售后</button></div><div v-for="item in afterSales" :key="item.id" class="after-sale-row"><span class="status-pill">{{ afterSaleStatus(item.status) }}</span><div><strong>{{ afterSaleKind(item.kind) }}</strong><p>{{ item.reason }}</p><small>{{ item.id }} · {{ new Date(item.created_at).toLocaleString() }}</small></div></div><p v-if="!afterSales.length" class="muted">该订单暂无售后记录。</p></article>
          <article class="panel actions wide"><h2>订单操作</h2><button v-if="canCancel" class="danger-outline" @click="navigate(`/me/orders/${order.id}/cancel`)">取消订单</button><span v-else class="muted">当前没有其他可用操作</span></article>
        </section>

        <section v-else class="operation-layout">
          <article class="panel order-summary"><span>{{ order.status_label }}</span><h2>{{ order.items.map((item) => item.product_name).join('、') }}</h2><p>订单 {{ order.id }} · ¥{{ order.total_amount.toFixed(2) }}</p></article>
          <article v-if="operation === 'cancel'" class="panel operation-panel"><h2>确认取消</h2><p>{{ canCancel ? '提交前已重新读取订单状态。取消成功后不可恢复。' : '订单当前状态不能直接取消。' }}</p><button class="danger" :disabled="loading || !canCancel" @click="submitCancel">确认取消订单</button></article>
          <form v-else-if="operation === 'address'" class="panel operation-panel" @submit.prevent="canEditAddress && submitAddress()"><h2>新的收货地址</h2><p v-if="!canEditAddress">订单当前状态不能修改收货地址。</p><label>详细地址<textarea v-model="form.address" rows="4" minlength="5" maxlength="300" required :disabled="!canEditAddress" /></label><button :disabled="loading || !canEditAddress">保存地址</button></form>
          <form v-else class="panel operation-panel" @submit.prevent="canApplyAfterSale && submitAfterSale()"><h2>售后信息</h2><p v-if="!canApplyAfterSale">该订单当前不能发起售后申请。</p><label>售后类型<select v-model="form.kind" :disabled="!canApplyAfterSale"><option value="refund">仅退款</option><option value="return">退货退款</option><option value="exchange">换货</option></select></label><label>问题描述<textarea v-model="form.reason" rows="5" minlength="2" maxlength="300" placeholder="请说明实际情况" required :disabled="!canApplyAfterSale" /></label><button :disabled="loading || !canApplyAfterSale">提交售后申请</button></form>
        </section>
      </template>
    </main>
  </div>
</template>


