// Fixed service date keeps the warranty examples reproducible.
export const serviceDate = '2026-11-21'
export const storageKey = 'demo.appliance.prototype.v1'
export const devices = [
  { id: 'w1', name: '滚筒洗衣机', model: 'W-DEMO', sn: 'DEMO-W-0101', signed: '2025-06-15', months: 12 },
  { id: 'w2', name: '滚筒洗衣机', model: 'W-DEMO', sn: 'DEMO-W-0102', signed: null, months: 12 },
  { id: 'a1', name: '壁挂式空调', model: 'A-DEMO', sn: 'DEMO-A-0201', signed: '2025-06-15', months: 24 },
]
export const manuals = {
  'W-DEMO': { title: '排水阶段未完成', source: 'DEMO 洗衣机说明书 · W-DEMO · 第 2 页 · E3', steps: ['从外部观察排水管是否被物品压住，不移动设备或拆卸管路。', '在显示面板查看排水程序是否被暂停。'] },
  'A-DEMO': { title: '进风区域受阻', source: 'DEMO 空调说明书 · A-DEMO · 第 3 页 · E3', steps: ['从安全位置观察进风口附近是否有窗帘遮挡。', '查看遥控器上当前送风模式的显示。'] },
}
export function warranty(d) {
  if (!d.signed) return { status: '待核验', notice: '签收日期缺失，保修资格待人工核验' }
  const end = new Date(d.signed + 'T00:00:00Z')
  end.setUTCMonth(end.getUTCMonth() + d.months)
  return serviceDate >= end.toISOString().slice(0, 10)
    ? { status: '已过保', notice: '已过保，维修费用待人工确认' }
    : { status: '在保', notice: '设备处于整机保修期，维修资格以人工核验为准。' }
}
export const timestamp = () => new Date().toISOString()
export const formatTime = value => new Date(value).toLocaleString('zh-CN', { hour12: false })
export function initial() {
  return { deviceId: null, phase: 'idle', description: '', code: '', step: 0, results: [], messages: [], preview: null, tickets: [], handoff: null }
}
export function message(state, role, text) {
  state.messages.push({ id: crypto.randomUUID(), role, text, at: timestamp() })
}
export function consult(s, input) {
  const text = input.trim()
  if (!text) return
  message(s, '用户', text)
  const smoke = text.includes('正在冒烟') && !/没有正在冒烟|如果.*正在冒烟/.test(text)
  if (smoke || text === '转人工') {
    if (!s.handoff) s.handoff = { status: 'WAITING', risk: false, reason: text, at: timestamp() }
    if (smoke) { s.handoff.risk = true; s.handoff.reason = text }
    if (!s.description) s.description = text
    if (/E3/i.test(text)) s.code = 'E3'
    s.phase = 'human'
    s.preview = null
    message(s, '助手', smoke ? '请停止使用设备，已为您转接人工客服。' : '已为您转接人工客服。')
    return
  }
  if (s.handoff) return
  s.description = text
  s.code = /\bE\d+\b/i.exec(text)?.[0].toUpperCase() || (/E3/i.test(text) ? 'E3' : '')
  s.results = []
  s.step = 0
  s.preview = null
  if (s.deviceId) diagnose(s)
  else { s.phase = 'choose'; message(s, '助手', '请对照机身序列号，选择本次需要咨询的设备。') }
}
function diagnose(s) {
  const d = devices.find(item => item.id === s.deviceId)
  if (s.code === 'E3') {
    s.phase = 'steps'
    const m = manuals[d.model]
    message(s, '助手', d.model + ' · E3：' + m.title + '。依据：' + m.source)
  } else {
    s.phase = 'repair'
    message(s, '助手', '当前 DEMO 资料未匹配到可引用的条目。请补充故障码，也可申请维修或转人工。')
  }
}
export function selectDevice(s, id) {
  if (s.handoff || !devices.some(d => d.id === id)) return
  s.deviceId = id
  s.step = 0
  s.results = []
  s.preview = null
  message(s, '用户', '选择设备 ' + devices.find(d => d.id === id).sn)
  diagnose(s)
}
export function feedback(s, recovered) {
  if (s.phase !== 'steps') return
  const m = manuals[devices.find(d => d.id === s.deviceId).model]
  const result = recovered ? '已恢复' : '未恢复'
  s.results.push({ text: m.steps[s.step], result })
  message(s, '用户', m.steps[s.step] + ' — ' + result)
  s.step++
  if (recovered || s.step === m.steps.length) {
    s.phase = recovered ? 'done' : 'repair'
    message(s, '助手', recovered ? '设备已恢复，本次自查结束。' : '说明书中的自查步骤已完成，可核对维修工单预览。')
  }
}
export function openPreview(s) {
  if (!s.deviceId || s.handoff) return
  if (s.tickets.some(t => t.deviceId === s.deviceId)) return 'existing'
  s.preview = { id: crypto.randomUUID(), deviceId: s.deviceId, description: s.description }
  return 'preview'
}
export function confirmPreview(s, id) {
  const p = s.preview
  if (!p || p.id !== id || s.handoff) return
  if (!s.tickets.some(t => t.deviceId === p.deviceId)) {
    const ticket = { id: 'DEMO-R-' + String(s.tickets.length + 1).padStart(4, '0'), deviceId: p.deviceId, description: p.description, at: timestamp(), status: '待受理' }
    s.tickets.unshift(ticket)
    message(s, '助手', '维修工单 ' + ticket.id + ' 已创建，当前状态：待受理。')
  }
  s.preview = null
  s.phase = 'done'
}
