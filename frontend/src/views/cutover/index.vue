<template>
  <section class="page" data-module="cutover">
    <header class="page-head">
      <div>
        <h2>割接变更工单</h2>
        <p class="page-desc">
          按站点和网元开单，变更窗口定下即锁定；挪时间只能重新报一次，同网元同窗口只认第一次报的那一版。
        </p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记割接工单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label class="filter-item">
        <span>关键字</span>
        <input v-model="filters.keyword" placeholder="按工单编号、网元、站点检索" />
      </label>
      <label class="filter-item">
        <span>状态</span>
        <select v-model="filters.status">
          <option value="">全部</option>
          <option v-for="s in STATUSES" :key="s" :value="s">{{ s }}</option>
        </select>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <p v-if="message" class="banner" :class="{ ok: messageOk }">{{ message }}</p>

    <div class="cutover-layout">
      <div class="list-col">
        <table class="data-table">
          <thead>
            <tr>
              <th>工单编号</th><th>站点</th><th>网元</th><th>变更窗口</th><th>影响面</th><th>状态</th><th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in rows" :key="String(row.id)" :class="{ active: detail && detail.id === row.id }">
              <td>{{ row.工单编号 || '—（打回单）' }}</td>
              <td>{{ row.站点 }}</td>
              <td>{{ row.网元 }}</td>
              <td>{{ row.窗口开始 }} ~ {{ row.窗口结束 }}</td>
              <td>{{ row.影响面 }}</td>
              <td><span class="status-chip" :data-status="row.status">{{ row.status }}</span></td>
              <td class="row-actions">
                <button class="link" type="button" @click="openDetail(Number(row.id))">办理</button>
              </td>
            </tr>
            <tr v-if="!rows.length">
              <td colspan="7" class="empty-state">暂无割接工单，可先登记割接工单</td>
            </tr>
          </tbody>
        </table>
        <footer class="page-foot">
          <span>共 {{ total }} 条割接工单</span>
        </footer>
      </div>

      <aside v-if="detail" class="detail-col">
        <header class="detail-head">
          <strong>{{ detail.工单编号 || '打回单' }}</strong>
          <span class="status-chip" :data-status="detail.status">{{ detail.status }}</span>
          <button class="link" type="button" @click="detail = null">关闭</button>
        </header>

        <div class="flow-bar">
          <span
            v-for="node in FLOW"
            :key="node"
            class="flow-node"
            :class="{ done: flowIndex(node) < flowIndex(detail.status), current: node === detail.status }"
          >{{ node }}</span>
          <span v-if="detail.status === '已回退'" class="flow-node current">已回退</span>
          <span v-if="detail.status === '已打回'" class="flow-node current">已打回</span>
          <span v-if="detail.status === '已作废'" class="flow-node current">已作废</span>
        </div>

        <dl class="info-grid">
          <dt>站点 / 网元</dt><dd>{{ detail.站点 }} / {{ detail.网元 }}</dd>
          <dt>变更窗口</dt>
          <dd>
            {{ detail.窗口开始 }} ~ {{ detail.窗口结束 }}
            <span v-if="detail.窗口锁定" class="lock-hint">已锁定，挪时间只能重新报</span>
          </dd>
          <dt>影响面</dt><dd>{{ detail.影响面 }}</dd>
          <dt>变更内容</dt><dd>{{ detail.变更内容 }}</dd>
          <dt>回退方案</dt><dd>{{ detail.回退方案 }}</dd>
          <dt v-if="detail.重报自">重报自</dt><dd v-if="detail.重报自">{{ detail.重报自 }}</dd>
          <dt v-if="detail.打回原因">打回原因</dt><dd v-if="detail.打回原因" class="warn-text">{{ detail.打回原因 }}</dd>
          <dt v-if="detail.作废说明">作废说明</dt><dd v-if="detail.作废说明" class="warn-text">{{ detail.作废说明 }}</dd>
          <dt v-if="detail.结论">结论</dt><dd v-if="detail.结论">{{ detail.结论 }}（{{ detail.完结时间 }}）</dd>
        </dl>

        <section v-if="(detail.会签存档 ?? []).length" class="block">
          <h4>会签存档（留档结论不随后续规则调整变化）</h4>
          <article v-for="round in detail.会签存档" :key="round.轮次" class="archive-card">
            <header>
              第 {{ round.轮次 }} 轮 · {{ round.结论 }} · 规则 {{ round.规则版本 }} · 归档于 {{ round.归档时间 }}
            </header>
            <p class="rule-text">{{ round.规则原文 }}</p>
            <ul>
              <li v-for="op in round.意见" :key="op.角色">
                {{ op.角色 }} {{ op.结论 }}：{{ op.意见 || '—' }}（{{ op.会签人 }} {{ op.时间 }}）
              </li>
            </ul>
          </article>
        </section>

        <section v-if="detail.status === '会签' && detail.当前会签" class="block">
          <h4>本轮会签（第 {{ detail.当前会签.轮次 }} 轮）</h4>
          <ul class="opinion-list">
            <li v-for="op in detail.当前会签.意见" :key="op.角色">
              {{ op.角色 }} {{ op.结论 }}：{{ op.意见 || '—' }}（{{ op.会签人 }} {{ op.时间 }}）
            </li>
            <li v-if="!(detail.当前会签.意见 ?? []).length">还没有会签意见</li>
          </ul>
          <form v-if="remainingRoles.length" class="inline-form" @submit.prevent="submitOpinion">
            <select v-model="opinionForm.role">
              <option v-for="role in remainingRoles" :key="role" :value="role">{{ role }}</option>
            </select>
            <select v-model="opinionForm.verdict">
              <option>通过</option>
              <option>驳回</option>
            </select>
            <input v-model="opinionForm.opinion" placeholder="会签意见（驳回必填）" />
            <button class="btn primary" type="submit">提交会签意见</button>
          </form>
          <p class="hint">{{ detail.会签规则 }}</p>
        </section>

        <section v-if="['执行中', '已完结', '已回退'].includes(detail.status)" class="block">
          <h4>执行环节（中断后重新进来，从还空着的环节接着填）</h4>
          <ol class="step-list">
            <li v-for="step in detail.执行环节" :key="step.环节" :class="{ done: !!step.确认时间 }">
              <template v-if="step.确认时间">
                ✓ {{ step.环节 }} · {{ step.结论 }} · {{ step.确认人 }} {{ step.确认时间 }}
                <span v-if="step.备注">（{{ step.备注 }}）</span>
              </template>
              <template v-else-if="detail.status === '执行中' && firstEmptyStep && step.环节 === firstEmptyStep.环节">
                <form class="inline-form" @submit.prevent="confirmStep(step.环节)">
                  <strong>{{ step.环节 }}</strong>
                  <select v-model="stepForm.结论">
                    <option>正常</option>
                    <option>异常</option>
                  </select>
                  <input v-model="stepForm.备注" placeholder="备注" />
                  <button class="btn primary" type="submit">确认本环节</button>
                </form>
              </template>
              <template v-else>○ {{ step.环节 }}（待确认）</template>
            </li>
          </ol>
        </section>

        <section class="block">
          <h4>操作</h4>
          <div class="action-row">
            <button v-if="detail.status === '立项'" class="btn primary" type="button" @click="runAction('提交会签')">提交会签</button>
            <button v-if="detail.status === '待执行'" class="btn primary" type="button" @click="runAction('开始执行')">开始执行</button>
            <button v-if="['立项', '会签', '待执行'].includes(detail.status)" class="btn" type="button" @click="toggleForm('rebook')">重新报窗口</button>
            <button v-if="detail.status === '执行中'" class="btn" type="button" @click="toggleForm('rollback')">执行回退</button>
            <button
              v-if="detail.status === '执行中'"
              class="btn primary"
              type="button"
              :disabled="!!firstEmptyStep"
              :title="firstEmptyStep ? '还有环节空着，不能完结' : ''"
              @click="toggleForm('finish')"
            >完结</button>
          </div>
          <form v-if="activeForm === 'rebook'" class="inline-form" @submit.prevent="submitRebook">
            <input v-model="rebookForm.start" type="datetime-local" />
            <input v-model="rebookForm.end" type="datetime-local" />
            <button class="btn primary" type="submit">确认改报</button>
            <span class="hint">原单作废留痕，新单重新走流程，原窗口不改动</span>
          </form>
          <form v-if="activeForm === 'rollback'" class="inline-form" @submit.prevent="submitRollback">
            <input v-model="rollbackConclusion" placeholder="回退结论（必填）" />
            <button class="btn primary" type="submit">确认回退</button>
          </form>
          <form v-if="activeForm === 'finish'" class="inline-form" @submit.prevent="submitFinish">
            <input v-model="finishConclusion" placeholder="收尾结论（必填）" />
            <button class="btn primary" type="submit">确认完结</button>
          </form>
        </section>

        <section v-if="(detail.流转记录 ?? []).length" class="block">
          <h4>流转记录</h4>
          <ul class="log-list">
            <li v-for="(log, i) in detail.流转记录" :key="i">
              {{ log.时间 }} · {{ log.动作 }} · {{ log.操作人 }} · {{ log.说明 }}
            </li>
          </ul>
        </section>

        <section class="block">
          <h4>网元最近变更（与网元台账页同一份数据）</h4>
          <ul v-if="(detail.网元最近变更 ?? []).length" class="log-list">
            <li v-for="change in detail.网元最近变更" :key="change.id">
              {{ change.时间 }} · {{ change.类型 }} · {{ change.结论 }}（{{ change.来源工单 }}）
            </li>
          </ul>
          <p v-else class="hint">该网元还没有变更记录</p>
        </section>
      </aside>
    </div>

    <div v-if="createOpen" class="modal-mask" @click.self="createOpen = false">
      <form class="modal-card" @submit.prevent="submitCreate">
        <h3>登记割接工单</h3>
        <label>站点<input v-model="createForm.站点" placeholder="如 SITE-0001" /></label>
        <label>网元
          <select v-model="createForm.网元">
            <option value="" disabled>选择网元</option>
            <option v-for="ne in neOptions" :key="ne.网元编号" :value="ne.网元编号">
              {{ ne.网元编号 }} · {{ ne.网元名称 }}
            </option>
          </select>
        </label>
        <label>变更内容<input v-model="createForm.变更内容" placeholder="本次割接要做什么" /></label>
        <label>影响面
          <select v-model="createForm.影响面">
            <option>高</option><option>中</option><option>低</option>
          </select>
        </label>
        <label>窗口开始<input v-model="createForm.窗口开始" type="datetime-local" /></label>
        <label>窗口结束<input v-model="createForm.窗口结束" type="datetime-local" /></label>
        <label>回退方案<input v-model="createForm.回退方案" placeholder="出问题怎么恢复" /></label>
        <p class="hint">窗口登记后即锁定；同网元同窗口重复提交会被原样打回。</p>
        <div class="action-row">
          <button class="btn primary" type="submit">提交登记</button>
          <button class="btn ghost" type="button" @click="createOpen = false">取消</button>
        </div>
      </form>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, any>

const ENDPOINT = '/api/cutover'
const STATUSES = ['立项', '会签', '待执行', '执行中', '已回退', '已完结', '已打回', '已作废']
const FLOW = ['立项', '会签', '待执行', '执行中', '已完结']

const rows = ref<Row[]>([])
const total = ref(0)
const stats = ref<{ label: string; value: number }[]>([])
const filters = ref({ keyword: '', status: '' })
const detail = ref<Row | null>(null)
const message = ref('')
const messageOk = ref(false)

const createOpen = ref(false)
const neOptions = ref<Row[]>([])
const createForm = ref({ 站点: '', 网元: '', 变更内容: '', 影响面: '中', 窗口开始: '', 窗口结束: '', 回退方案: '' })

const activeForm = ref('')
const rebookForm = ref({ start: '', end: '' })
const rollbackConclusion = ref('')
const finishConclusion = ref('')
const opinionForm = ref({ role: '', verdict: '通过', opinion: '' })
const stepForm = ref({ 结论: '正常', 备注: '' })

const remainingRoles = computed<string[]>(() => {
  if (!detail.value?.当前会签) return []
  const submitted = (detail.value.当前会签.意见 ?? []).map((op: Row) => op.角色)
  return (detail.value.会签角色 ?? []).filter((role: string) => !submitted.includes(role))
})

const firstEmptyStep = computed<Row | null>(() => {
  const steps: Row[] = detail.value?.执行环节 ?? []
  return steps.find((step) => !step.确认时间) ?? null
})

function flowIndex(status: string) {
  const index = FLOW.indexOf(status)
  return index === -1 ? FLOW.length : index
}

function toWindow(value: string) {
  return value.replace('T', ' ')
}

async function callJson(path: string, init?: RequestInit): Promise<Row> {
  const response = await request(path, init)
  return (await response.json().catch(() => ({}))) as Row
}

function showMessage(payload: Row) {
  message.value = String(payload.message ?? '')
  messageOk.value = !!payload.ok
}

async function reload() {
  const query = new URLSearchParams()
  if (filters.value.keyword) query.set('keyword', filters.value.keyword)
  if (filters.value.status) query.set('status', filters.value.status)
  const payload = await callJson(`${ENDPOINT}?${query}`)
  rows.value = payload.items ?? []
  total.value = payload.total ?? rows.value.length
  const all = await callJson(`${ENDPOINT}?size=200`)
  const items: Row[] = all.items ?? []
  const count = (status: string) => items.filter((row) => row.status === status).length
  stats.value = [
    { label: '在途工单', value: count('立项') + count('会签') + count('待执行') + count('执行中') },
    { label: '待执行', value: count('待执行') },
    { label: '执行中', value: count('执行中') },
    { label: '已回退', value: count('已回退') },
  ]
}

function resetFilters() {
  filters.value = { keyword: '', status: '' }
  void reload()
}

async function openDetail(id: number) {
  detail.value = await callJson(`${ENDPOINT}/${id}`)
  activeForm.value = ''
}

async function runAction(action: string, values: Row = {}) {
  if (!detail.value) return
  const payload = await callJson(`${ENDPOINT}/${detail.value.id}/actions`, {
    method: 'POST',
    body: JSON.stringify({ values: { action, ...values } }),
  })
  showMessage(payload)
  await reload()
  if (payload.entry?.id) {
    await openDetail(Number(payload.entry.id))
  } else if (detail.value) {
    await openDetail(Number(detail.value.id))
  }
}

function toggleForm(name: string) {
  activeForm.value = activeForm.value === name ? '' : name
}

async function submitOpinion() {
  await runAction('会签意见', {
    会签角色: opinionForm.value.role || remainingRoles.value[0],
    结论: opinionForm.value.verdict,
    意见: opinionForm.value.opinion,
  })
  opinionForm.value = { role: '', verdict: '通过', opinion: '' }
}

async function confirmStep(step: string) {
  await runAction('确认环节', { 环节: step, 结论: stepForm.value.结论, 备注: stepForm.value.备注 })
  stepForm.value = { 结论: '正常', 备注: '' }
}

async function submitRebook() {
  await runAction('重新报窗口', { 窗口开始: toWindow(rebookForm.value.start), 窗口结束: toWindow(rebookForm.value.end) })
  rebookForm.value = { start: '', end: '' }
}

async function submitRollback() {
  await runAction('执行回退', { 回退结论: rollbackConclusion.value })
  rollbackConclusion.value = ''
}

async function submitFinish() {
  await runAction('完结', { 收尾结论: finishConclusion.value })
  finishConclusion.value = ''
}

async function openCreate() {
  createOpen.value = true
  const payload = await callJson('/api/neledger')
  neOptions.value = payload.items ?? []
}

async function submitCreate() {
  const payload = await callJson(ENDPOINT, {
    method: 'POST',
    body: JSON.stringify({
      values: {
        ...createForm.value,
        窗口开始: toWindow(createForm.value.窗口开始),
        窗口结束: toWindow(createForm.value.窗口结束),
      },
    }),
  })
  showMessage(payload)
  if (payload.ok) {
    createOpen.value = false
    createForm.value = { 站点: '', 网元: '', 变更内容: '', 影响面: '中', 窗口开始: '', 窗口结束: '', 回退方案: '' }
  }
  await reload()
  if (payload.entry?.id) await openDetail(Number(payload.entry.id))
}

onMounted(reload)
</script>

<style scoped>
.cutover-layout { display: flex; gap: 16px; align-items: flex-start; }
.list-col { flex: 1; min-width: 0; }
.detail-col { width: 460px; background: #fff; border: 1px solid var(--border); border-radius: 8px; padding: 12px 14px; }
.detail-head { display: flex; gap: 8px; align-items: center; justify-content: space-between; margin-bottom: 8px; }
tr.active td { background: #eff6ff; }
.status-chip { font-size: 12px; padding: 2px 8px; border-radius: 10px; background: #eef2f7; }
.status-chip[data-status='执行中'] { background: #dbeafe; }
.status-chip[data-status='待执行'] { background: #dcfce7; }
.status-chip[data-status='已回退'], .status-chip[data-status='已打回'] { background: #fee2e2; }
.status-chip[data-status='已完结'] { background: #e2e8f0; }
.flow-bar { display: flex; gap: 4px; flex-wrap: wrap; margin-bottom: 10px; }
.flow-node { font-size: 12px; padding: 2px 8px; border-radius: 4px; border: 1px solid var(--border); color: var(--muted); }
.flow-node.done { background: #e0f2fe; color: #1f2937; }
.flow-node.current { background: var(--brand); border-color: var(--brand); color: #fff; }
.info-grid { display: grid; grid-template-columns: 88px 1fr; gap: 4px 8px; font-size: 13px; margin: 0 0 10px; }
.info-grid dt { color: var(--muted); }
.info-grid dd { margin: 0; }
.lock-hint { color: #b45309; font-size: 12px; margin-left: 6px; }
.warn-text { color: #b42318; }
.block { border-top: 1px dashed var(--border); padding-top: 8px; margin-top: 8px; }
.block h4 { margin: 0 0 6px; font-size: 13px; }
.archive-card { border: 1px solid var(--border); border-radius: 6px; padding: 6px 8px; margin-bottom: 6px; font-size: 12px; }
.archive-card header { font-weight: 600; }
.rule-text { color: var(--muted); margin: 4px 0; }
.archive-card ul, .opinion-list, .log-list { margin: 4px 0; padding-left: 18px; font-size: 12px; }
.step-list { margin: 0; padding-left: 20px; font-size: 13px; }
.step-list li { margin-bottom: 6px; }
.step-list li.done { color: var(--muted); }
.inline-form { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; margin-top: 6px; }
.inline-form input, .inline-form select { padding: 4px 6px; border: 1px solid var(--border); border-radius: 4px; font-size: 12px; }
.action-row { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
.hint { color: var(--muted); font-size: 12px; }
.banner { padding: 8px 10px; border-radius: 6px; background: #fee2e2; font-size: 13px; }
.banner.ok { background: #dcfce7; }
.modal-mask { position: fixed; inset: 0; background: rgba(15, 23, 42, 0.4); display: flex; align-items: center; justify-content: center; }
.modal-card { background: #fff; border-radius: 8px; padding: 16px 18px; width: 420px; display: flex; flex-direction: column; gap: 8px; }
.modal-card h3 { margin: 0; }
.modal-card label { display: flex; flex-direction: column; font-size: 12px; color: var(--muted); gap: 2px; }
.modal-card input, .modal-card select { padding: 6px 8px; border: 1px solid var(--border); border-radius: 4px; }
</style>
