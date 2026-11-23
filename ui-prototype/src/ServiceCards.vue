<script setup>
import { devices, manuals, warranty } from './demo.js'
defineProps(['kind','device','session'])
defineEmits(['select','feedback','confirm','close'])
</script>
<template>
  <div v-if="kind === 'devices'" class="choice-list">
    <button v-for="d in devices" :key="d.id" @click="$emit('select',d.id)">
      <span><strong>{{ d.name }} · {{ d.model }}</strong><small>{{ d.sn }}</small></span><b>→</b>
    </button>
  </div>
  <div v-else-if="kind === 'step' && device" class="diagnosis">
    <small>用户自查 · {{ session.step + 1 }} / {{ manuals[device.model].steps.length }}</small>
    <h3>{{ manuals[device.model].steps[session.step] }}</h3>
    <p>来源：{{ manuals[device.model].source }}</p>
    <div class="actions"><button @click="$emit('feedback',true)">已恢复</button><button class="accent" @click="$emit('feedback',false)">未恢复 →</button></div>
  </div>
  <div v-else-if="kind === 'preview' && session.preview && device">
    <dl><dt>设备</dt><dd>{{ device.name }} · {{ device.model }}</dd><dt>序列号</dt><dd>{{ device.sn }}</dd>
      <dt>故障描述</dt><dd>{{ session.preview.description }}</dd><dt>签收日</dt><dd>{{ device.signed || '缺少记录' }}</dd>
      <dt>整机保修</dt><dd>{{ device.months }} 个月 · {{ warranty(device).status }}</dd></dl>
    <p class="notice">{{ warranty(device).notice }}</p>
    <div class="actions"><button @click="$emit('close')">返回咨询</button><button class="accent" @click="$emit('confirm',session.preview.id)">确认提交维修申请</button></div>
  </div>
</template>
