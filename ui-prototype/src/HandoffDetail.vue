<script>
export default {
  props: ['session', 'device', 'ticket', 'formatTime'],
  emits: ['accept', 'reply', 'example'],
  data: () => ({ reply: '' }),
  methods: {
    send() {
      const value = this.reply.trim()
      if (value) { this.$emit('reply', value); this.reply = '' }
    },
  },
}
</script>
<template>
  <section v-if="!session.handoff" class="proto-panel empty">
    <h2>暂无待接入会话</h2><p>用户报告“正在冒烟”或主动要求人工服务后，交接资料会出现在这里。</p>
    <button class="accent" @click="$emit('example')">模拟用户报告正在冒烟</button>
  </section>
  <div v-else class="proto-columns">
    <section class="proto-panel">
      <div class="section-head"><h2>人工接入详情</h2><span class="pill">{{ session.handoff.status === 'WAITING' ? '等待接入' : '接待中' }}</span></div>
      <div class="block"><h3>交接摘要</h3><p>{{ session.handoff.reason }}</p>
        <p :class="{ warning: session.handoff.risk }">安全风险 · {{ session.handoff.risk ? '正在冒烟，已停止自查' : '无已报告风险' }}</p>
        <dl><dt>设备</dt><dd>{{ device ? device.name + ' · ' + device.model + ' · ' + device.sn : '设备未确认' }}</dd>
          <dt>故障码</dt><dd>{{ session.code || '未知' }}</dd><dt>用户描述</dt><dd>{{ session.description }}</dd></dl>
        <h3>已执行步骤与结果</h3><p v-if="!session.results.length">暂无已反馈步骤</p>
        <p v-for="(r,i) in session.results" :key="i">{{ i+1 }}. {{ r.text }} · <strong>{{ r.result }}</strong></p>
        <h3>已有维修工单</h3><template v-if="ticket"><p>{{ ticket.id }} · {{ ticket.status }}</p><p>{{ device.sn }} · {{ ticket.description }}</p><small>{{ formatTime(ticket.at) }}</small></template>
        <p v-else>{{ device ? '该设备暂无待受理工单' : '设备未确认，无法关联维修工单' }}</p>
      </div>
    </section>
    <section class="proto-panel"><div class="section-head"><h2>聊天记录</h2></div>
      <div class="staff-log"><p v-for="m in session.messages" :key="m.id"><small>{{ m.role }} · {{ formatTime(m.at) }}</small><br>{{ m.text }}</p></div>
      <form class="block reply" @submit.prevent="send"><label for="staff-reply">客服回复</label>
        <textarea id="staff-reply" v-model="reply" :disabled="session.handoff.status !== 'ACTIVE'" placeholder="输入回复内容"></textarea>
        <button v-if="session.handoff.status === 'WAITING'" type="button" class="accent" @click="$emit('accept')">接入会话</button>
        <button v-else class="accent" :disabled="!reply.trim()">发送回复</button>
      </form>
    </section>
  </div>
</template>
