<template>
  <section class="page" data-module="neledger">
    <header class="page-head">
      <div>
        <h2>网元台账</h2>
        <p class="page-desc">
          割接收尾/回退结论只回写到这一本台账；割接工单详情里读到的最近变更也是这一份。
          同一网元上割接、巡检、告警处理互相让路，谁先谁后由排期服务统一裁决。
        </p>
      </div>
    </header>

    <form class="filter-bar" @submit.prevent="reload">
      <label class="filter-item">
        <span>关键字</span>
        <input v-model="keyword" placeholder="按网元编号、网元名称检索" />
      </label>
      <button class="btn" type="submit">查询</button>
    </form>

    <p v-if="message" class="banner" :class="{ ok: messageOk }">{{ message }}</p>

    <div class="ne-layout">
      <div class="list-col">
        <table class="data-table">
          <thead>
            <tr>
              <th>网元编号</th><th>网元名称</th><th>网元类型</th><th>所属站点</th><th>当前状态</th><th>最近变更时间</th><th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in nes" :key="row.网元编号" :class="{ active: current && current.网元编号 === row.网元编号 }">
              <td>{{ row.网元编号 }}</td>
              <td>{{ row.网元名称 }}</td>
              <td>{{ row.网元类型 }}</td>
              <td>{{ row.所属站点 }}</td>
              <td>{{ row.当前状态 }}</td>
              <td>{{ row.最近变更时间 }}</td>
              <td class="row-actions">
                <button class="link" type="button" @click="openNe(row.网元编号)">台账</button>
              </td>
            </tr>
            <tr v-if="!nes.length">
              <td colspan="7" class="empty-state">暂无网元台账数据</td>
            </tr>
          </tbody>
        </table>
      </div>

      <aside v-if="current" class="detail-col">
        <header class="detail-head">
          <strong>{{ current.网元编号 }} · {{ current.网元名称 }}</strong>
          <button class="link" type="button" @click="current = null">关闭</button>
        </header>

        <section class="block">
          <h4>最近变更</h4>
          <ul v-if="(current.最近变更 ?? []).length" class="log-list">
            <li v-for="change in current.最近变更" :key="change.id">
              {{ change.时间 }} · {{ change.类型 }} · {{ change.结论 }}
              <span class="hint">（{{ change.来源工单 }} · {{ change.变更窗口 }}）</span>
            </li>
          </ul>
          <p v-else class="hint">该网元还没有变更记录</p>
        </section>

        <section class="block">
          <h4>窗口占用（影响面大的先排，同级先报先得）</h4>
          <table class="data-table">
            <thead>
              <tr><th>类型</th><th>事项</th><th>窗口</th><th>影响面</th><th>状态</th></tr>
            </thead>
            <tbody>
              <tr v-for="booking in bookings" :key="booking.id">
                <td>{{ booking.类型 }}</td>
                <td>
                  {{ booking.事项 }}
                  <div v-if="booking.让路说明" class="hint">{{ booking.让路说明 }}</div>
                </td>
                <td>{{ booking.窗口开始 }} ~ {{ booking.窗口结束 }}</td>
                <td>{{ booking.影响面 }}</td>
                <td>{{ booking.状态 }}</td>
              </tr>
              <tr v-if="!bookings.length">
                <td colspan="5" class="empty-state">该网元暂无窗口占用</td>
              </tr>
            </tbody>
          </table>
        </section>

        <section class="block">
          <h4>登记占用（巡检 / 告警处理）</h4>
          <form class="inline-form" @submit.prevent="submitBooking">
            <select v-model="bookingForm.类型">
              <option>巡检</option>
              <option>告警处理</option>
            </select>
            <input v-model="bookingForm.事项" placeholder="事项" />
            <select v-model="bookingForm.影响面">
              <option>高</option><option>中</option><option>低</option>
            </select>
            <input v-model="bookingForm.窗口开始" type="datetime-local" />
            <input v-model="bookingForm.窗口结束" type="datetime-local" />
            <button class="btn primary" type="submit">登记占用</button>
          </form>
          <p class="hint">割接占用请走割接工单登记；与已有占用冲突时按统一口径裁决谁让路。</p>
        </section>
      </aside>
    </div>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, any>

const nes = ref<Row[]>([])
const current = ref<Row | null>(null)
const bookings = ref<Row[]>([])
const keyword = ref('')
const message = ref('')
const messageOk = ref(false)
const bookingForm = ref({ 类型: '巡检', 事项: '', 影响面: '低', 窗口开始: '', 窗口结束: '' })

function toWindow(value: string) {
  return value.replace('T', ' ')
}

async function callJson(path: string, init?: RequestInit): Promise<Row> {
  const response = await request(path, init)
  return (await response.json().catch(() => ({}))) as Row
}

async function reload() {
  const query = keyword.value ? `?keyword=${encodeURIComponent(keyword.value)}` : ''
  const payload = await callJson(`/api/neledger${query}`)
  nes.value = payload.items ?? []
}

async function openNe(neId: string) {
  current.value = await callJson(`/api/neledger/${encodeURIComponent(neId)}`)
  const payload = await callJson(`/api/schedule?ne=${encodeURIComponent(neId)}`)
  bookings.value = payload.items ?? []
}

async function submitBooking() {
  if (!current.value) return
  const payload = await callJson('/api/schedule/book', {
    method: 'POST',
    body: JSON.stringify({
      values: {
        ...bookingForm.value,
        网元: current.value.网元编号,
        窗口开始: toWindow(bookingForm.value.窗口开始),
        窗口结束: toWindow(bookingForm.value.窗口结束),
      },
    }),
  })
  message.value = String(payload.message ?? '')
  messageOk.value = !!payload.ok
  bookingForm.value = { 类型: '巡检', 事项: '', 影响面: '低', 窗口开始: '', 窗口结束: '' }
  await openNe(String(current.value.网元编号))
}

onMounted(reload)
</script>

<style scoped>
.ne-layout { display: flex; gap: 16px; align-items: flex-start; }
.list-col { flex: 1; min-width: 0; }
.detail-col { width: 520px; background: #fff; border: 1px solid var(--border); border-radius: 8px; padding: 12px 14px; }
.detail-head { display: flex; gap: 8px; align-items: center; justify-content: space-between; margin-bottom: 8px; }
tr.active td { background: #eff6ff; }
.block { border-top: 1px dashed var(--border); padding-top: 8px; margin-top: 8px; }
.block h4 { margin: 0 0 6px; font-size: 13px; }
.log-list { margin: 4px 0; padding-left: 18px; font-size: 12px; }
.inline-form { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
.inline-form input, .inline-form select { padding: 4px 6px; border: 1px solid var(--border); border-radius: 4px; font-size: 12px; }
.hint { color: var(--muted); font-size: 12px; }
.banner { padding: 8px 10px; border-radius: 6px; background: #fee2e2; font-size: 13px; }
.banner.ok { background: #dcfce7; }
</style>
