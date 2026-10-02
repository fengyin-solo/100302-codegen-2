<template>
  <section class="page" data-module="element">
    <header class="page-head">
      <div>
        <h2>网元台账</h2>
        <p class="page-desc">
          每个网元的最近一次割接收尾/回退结论在这里回写留底；
          割接工单页读到的「最近变更」与本页是同一份数据，不存在两套口径。
        </p>
      </div>
    </header>

    <form class="filter-bar" @submit.prevent="reload">
      <label class="filter-item"><span>网元编号 / 名称</span><input v-model="filters.keyword" placeholder="按网元检索" /></label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="filters.keyword = ''; void reload()">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="col in columns" :key="col">{{ col }}</th>
          <th>操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td>{{ row['网元编号'] }}</td>
          <td>{{ row['网元名称'] || '—' }}</td>
          <td>{{ row['所属站点'] }}</td>
          <td>{{ row['网元类型'] || '—' }}</td>
          <td><span class="badge badge-green">{{ row['网元状态'] }}</span></td>
          <td>{{ row['最近变更工单号'] || '—' }}</td>
          <td>{{ row['最近变更类型'] || '—' }}</td>
          <td>
            <span v-if="row['最近变更结果']" class="badge"
              :class="row['最近变更结果'] === '已完结' ? 'badge-green' : 'badge-red'">
              {{ row['最近变更结果'] }}
            </span>
            <span v-else>—</span>
          </td>
          <td>{{ row['最近变更结论'] || '—' }}</td>
          <td>{{ row['最近变更时间'] || '—' }}</td>
          <td><button class="link" type="button" @click="openLatest(row)">核对同源</button></td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无网元台账数据</td>
        </tr>
      </tbody>
    </table>
    <footer class="page-foot">
      <span>共 {{ total }} 个网元</span>
      <span v-if="message" class="error-text">{{ message }}</span>
    </footer>

    <div v-if="latest" class="modal-mask" @click.self="latest = null">
      <div class="modal" style="width:min(560px,96vw)">
        <div class="modal-head">
          <h3>最近变更同源核对 · {{ latest['网元编号'] }}</h3>
          <button class="modal-close" type="button" @click="latest = null">×</button>
        </div>
        <p class="subtle">下方数据来自台账入口接口，割接工单页 /api/cutover/elements 取到的是同一份。</p>
        <dl class="kv-grid" style="grid-template-columns:120px 1fr">
          <dt>最近工单</dt><dd>{{ latest['最近变更工单号'] }}</dd>
          <dt>变更类型</dt><dd>{{ latest['最近变更类型'] }}</dd>
          <dt>变更结果</dt><dd>
            <span class="badge" :class="latest['最近变更结果'] === '已完结' ? 'badge-green' : 'badge-red'">
              {{ latest['最近变更结果'] }}
            </span>
          </dd>
          <dt>结论</dt><dd>{{ latest['最近变更结论'] }}</dd>
          <dt>时间</dt><dd>{{ latest['最近变更时间'] }}</dd>
          <dt>数据来源</dt><dd>{{ latest['数据来源'] }}</dd>
        </dl>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'

import { request } from '@/api/client'

type Rec = Record<string, any>

const ENDPOINT = '/api/element'
const columns = ['网元编号', '网元名称', '所属站点', '网元类型', '网元状态',
  '最近变更工单号', '最近变更类型', '最近变更结果', '最近变更结论', '最近变更时间']

const rows = ref<Rec[]>([])
const total = ref(0)
const message = ref('')
const filters = reactive({ keyword: '' })
const latest = ref<Rec | null>(null)

async function reload() {
  message.value = ''
  const q = new URLSearchParams()
  if (filters.keyword) q.set('keyword', filters.keyword)
  const resp = await request(`${ENDPOINT}?${q.toString()}`)
  if (!resp.ok) {
    message.value = '网元台账读取失败'
    return
  }
  const data = await resp.json()
  rows.value = data.items ?? []
  total.value = data.total ?? 0
}

async function openLatest(row: Rec) {
  message.value = ''
  const resp = await request(`${ENDPOINT}/code/${encodeURIComponent(row['网元编号'])}/latest-change`)
  if (!resp.ok) {
    message.value = '该网元暂无变更记录'
    return
  }
  latest.value = await resp.json()
}

onMounted(reload)
</script>
