import DOMPurify from 'dompurify'
import { marked } from 'marked'
marked.setOptions({ gfm: true, breaks: true })
export function messageText(message) {
  const content = message.content || {}
  if (content.text) return content.text
  if (Array.isArray(content.blocks)) return content.blocks.map((block) => block.content).join('\n\n')
  if (content.object_type === 'order') return `已发送订单 ${content.object_id}`
  if (content.object_type === 'product') return `已发送商品 ${content.object_id}`
  if (content.outcome) return content.outcome === 'resolved' ? '已恢复' : '未恢复'
  if (content.device_id) return '选择设备 ' + content.device_id
  return '暂不支持的消息' 
}

export function messageHtml(message) {
  return DOMPurify.sanitize(marked.parse(messageText(message)), {
    USE_PROFILES: { html: true }
  })
}

