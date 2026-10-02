<template>
  <section class="page" data-module="cutover">
    <header class="page-head">
      <div>
        <h2>网络变更与割接工单</h2>
        <p class="page-desc">
          按站点与网元开单，窗口立项即锁死，挪窗只能重新报；同网元同窗口重复提交只认第一版；
          会签通过才放行，执行环节断点续作，收尾/回退结论回写网元台账。
        </p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">新立割接工单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <div class="tab-bar">
      <button v-for="tab in tabs" :key="tab.key" class="tab" :class="{ active: activeTab === tab.key }"
        type="button" @click="switchTab(tab.key)">{{ tab.label }}</button>
    </div>

    <!-- 工单列表 -->
    <template v-if="activeTab === 'orders'">
      <form class="filter-bar" @submit.prevent="reloadOrders">
        <label class="filter-item"><span>工单号</span><input v-model="orderFilter.keyword" placeholder="按工单号检索" /></label>
        <label class="filter-item"><span>网元编号</span><input v-model="orderFilter.element" placeholder="按网元编号" /></label>
        <label class="filter-item"><span>状态</span>
          <select v-model="orderFilter.status">
            <option value="">全部</option>
            <option v-for="s in statuses" :key="s" :value="s">{{ s }}</option>
          </select>
        </label>
        <button class="btn" type="submit">查询</button>
        <button class="btn ghost" type="button" @click="resetOrderFilter">重置条件</button>
      </form>

      <table class="data-table">
        <thead>
          <tr>
            <th v-for="col in orderColumns" :key="col">{{ col }}</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in orders" :key="String(row.id)">
            <td>{{ row['工单号'] }}</td>
            <td>{{ row['所属站点'] }}</td>
            <td>{{ row['网元编号'] }}</td>
            <td>{{ row['变更类型'] }}</td>
            <td>{{ row['窗口开始'] }} ~<br />{{ row['窗口结束'] }}</td>
            <td>
              <span v-if="row['源工单号']" class="subtle">重报自 {{ row['源工单号'] }}</span>
              <span v-else>—</span>
            </td>
            <td><span class="badge" :class="statusClass(String(row.status))">{{ row.status }}</span></td>
            <td class="row-actions">
              <button class="link" type="button" @click="openDetail(row)">详情</button>
              <button class="link" type="button" @click="openAction(row)">{{ actionLabel(row) }}</button>
            </td>
          </tr>
          <tr v-if="!orders.length">
            <td :colspan="orderColumns.length + 1" class="empty-state">暂无符合条件的割接工单</td>
          </tr>
        </tbody>
      </table>
      <footer class="page-foot">
        <span>共 {{ orderTotal }} 张割接工单</span>
        <span v-if="message" :class="messageOk ? 'ok-text' : 'error-text'">{{ message }}</span>
      </footer>
    </template>

    <!-- 让行排程 -->
    <template v-else-if="activeTab === 'schedule'">
      <div class="page-head">
        <p class="page-desc">{{ scheduleData['让行规则']?.['规则说明'] }}（顺序只在后端 scheduling 一处定义）</p>
        <div class="page-actions">
          <button class="btn" type="button" @click="openTask">登记巡检/告警作业</button>
        </div>
      </div>
      <div v-if="scheduleData['让行规则']" class="frozen-box">
        影响面次序：
        <span v-for="(r, i) in scheduleData['让行规则']['影响面次序']" :key="r['作业类型']">
          {{ i + 1 }}.{{ r['作业类型'] }}（{{ r['说明'] }}）<span v-if="i < 2">＞</span>
        </span>
      </div>
      <div v-for="group in scheduleData['分组']" :key="group['网元编号']" style="margin-top:14px">
        <h3 class="section-title">网元 {{ group['网元编号'] }}
          <span v-if="group['冲突数']" class="badge badge-red" style="margin-left:8px">{{ group['冲突数'] }} 件窗口重叠需让行</span>
        </h3>
        <table class="data-table">
          <thead>
            <tr><th>次序</th><th>作业类型</th><th>作业编号</th><th>作业标题</th><th>窗口</th><th>提交时间</th><th>让路</th></tr>
          </thead>
          <tbody>
            <tr v-for="t in group['任务']" :key="String(t['作业编号'])">
              <td>{{ t['排序位次'] }}</td>
              <td><span :class="`prio-${t['影响面']}`">{{ t['作业类型'] }}</span></td>
              <td>{{ t['作业编号'] }}</td>
              <td>{{ t['作业标题'] }}</td>
              <td>{{ t['窗口开始'] }} ~ {{ t['窗口结束'] }}</td>
              <td>{{ t['提交时间'] }}</td>
              <td>
                <span v-if="t['让路给']?.length" class="badge badge-amber">让给 {{ t['让路给'].join('、') }}</span>
                <span v-else class="subtle">先排</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <p v-if="!scheduleData['分组']?.length" class="empty-state">暂无同窗口作业</p>
    </template>

    <!-- 打回记录 -->
    <template v-else>
      <table class="data-table">
        <thead>
          <tr><th>打回工单号</th><th>网元</th><th>变更类型</th><th>申请窗口</th><th>提报人/时间</th><th>中标工单</th><th>打回原因</th></tr>
        </thead>
        <tbody>
          <tr v-for="r in rejected" :key="String(r.id)">
            <td><span class="badge badge-red">{{ r['打回工单号'] }}</span></td>
            <td>{{ r['网元编号'] }}</td>
            <td>{{ r['变更类型'] }}</td>
            <td>{{ r['窗口开始'] }} ~ {{ r['窗口结束'] }}</td>
            <td>{{ r['提报人'] }}<br /><span class="subtle">{{ r['提报时间'] }}</span></td>
            <td>{{ r['中标工单号'] }}</td>
            <td>{{ r['打回原因'] }}</td>
          </tr>
          <tr v-if="!rejected.length"><td colspan="7" class="empty-state">暂无重复打回记录</td></tr>
        </tbody>
      </table>
    </template>

    <!-- 新建工单 -->
    <div v-if="showCreate" class="modal-mask" @click.self="showCreate = false">
      <div class="modal">
        <div class="modal-head">
          <h3>新立割接工单（窗口立项即锁死）</h3>
          <button class="modal-close" type="button" @click="showCreate = false">×</button>
        </div>
        <div class="lock-note">变更窗口一旦定下不允许在原单上修改；要挪时间请在工单上走「重新报窗」，系统会新开一单并保留原单。</div>
        <form class="form-grid" @submit.prevent="submitCreate">
          <label><span>所属站点 *</span><input v-model="createForm['所属站点']" /></label>
          <label><span>网元编号 *</span><input v-model="createForm['网元编号']" /></label>
          <label><span>变更类型 *</span><input v-model="createForm['变更类型']" placeholder="如：传输链路割接" /></label>
          <label><span>提报人 *</span><input v-model="createForm['提报人']" /></label>
          <label><span>窗口开始 *</span><input v-model="createForm['窗口开始']" type="datetime-local" /></label>
          <label><span>窗口结束 *</span><input v-model="createForm['窗口结束']" type="datetime-local" /></label>
          <label class="full"><span>变更内容 *</span><textarea v-model="createForm['变更内容']"></textarea></label>
          <label class="full"><span>回退方案 *（会签后原样留档）</span><textarea v-model="createForm['回退方案']"></textarea></label>
          <div class="modal-foot full">
            <span v-if="modalError" class="error-text">{{ modalError }}</span>
            <button class="btn ghost" type="button" @click="showCreate = false">取消</button>
            <button class="btn primary" type="submit">立项开单</button>
          </div>
        </form>
      </div>
    </div>

    <!-- 工单详情/操作 -->
    <div v-if="current" class="modal-mask" @click.self="current = null">
      <div class="modal">
        <div class="modal-head">
          <h3>{{ current['工单号'] }}
            <span class="badge" :class="statusClass(String(current.status))" style="margin-left:8px">{{ current.status }}</span>
            <span v-if="current['源工单号']" class="subtle" style="margin-left:8px">重新报窗自 {{ current['源工单号'] }}</span>
          </h3>
          <button class="modal-close" type="button" @click="current = null">×</button>
        </div>

        <dl class="kv-grid">
          <dt>所属站点</dt><dd>{{ current['所属站点'] }}</dd>
          <dt>网元编号</dt><dd>{{ current['网元编号'] }}</dd>
          <dt>变更类型</dt><dd>{{ current['变更类型'] }}</dd>
          <dt>提报人</dt><dd>{{ current['提报人'] }}</dd>
          <dt>变更窗口</dt><dd class="full">{{ current['窗口开始'] }} ~ {{ current['窗口结束'] }}（已锁定）</dd>
          <dt>变更内容</dt><dd class="full">{{ current['变更内容'] }}</dd>
          <dt>回退方案</dt><dd class="full">{{ current['回退方案'] }}</dd>
        </dl>

        <!-- 会签 -->
        <h4 class="section-title">三方会签{{ current['会签留档'] ? '（结论已留档冻结）' : '' }}</h4>
        <ul class="timeline">
          <li v-for="seat in current['会签席位']" :key="seat['席位']" :class="seat['结论'] === '通过' ? 'done' : seat['结论'] === '驳回' ? '' : ''">
            <strong>{{ seat['席位'] }}</strong>
            <span v-if="seat['结论']" class="badge" :class="seat['结论'] === '通过' ? 'badge-green' : 'badge-red'" style="margin-left:6px">
              {{ seat['结论'] }}
            </span>
            <span v-else class="badge badge-gray" style="margin-left:6px">待签署</span>
            <div class="tl-meta">
              {{ seat['意见'] || '—' }}
              <span v-if="seat['签署人']"> · {{ seat['签署人'] }} · {{ seat['签署时间'] }}</span>
            </div>
          </li>
        </ul>
        <div v-if="current.status === '会签中'" class="seat-row">
          <select v-model="signForm.seat">
            <option v-for="s in availableSeats" :key="s" :value="s">{{ s }}</option>
          </select>
          <select v-model="signForm.result">
            <option value="通过">通过</option>
            <option value="驳回">驳回</option>
          </select>
          <input v-model="signForm.signer" placeholder="签署人" style="width:110px" />
          <input v-model="signForm.opinion" placeholder="会签意见" style="flex:1;min-width:160px" />
          <button class="btn primary" type="button" @click="doCountersign">提交签署</button>
        </div>
        <div v-if="current['会签留档']" class="frozen-box">
          留档规则版本：{{ current['会签留档']['规则版本'] }} · 留档时间：{{ current['会签留档']['留档时间'] }}<br />
          回退方案原文：{{ current['会签留档']['回退方案原文'] }}
        </div>

        <!-- 执行环节 -->
        <h4 class="section-title">执行环节（已确认不可改，中断后从空缺环节续作）</h4>
        <ul class="timeline">
          <li v-for="(step, i) in current['执行环节']" :key="step['环节']"
            :class="step['确认人'] ? 'done' : (isFirstEmpty(i) ? 'current' : '')">
            <strong>{{ i + 1 }}. {{ step['环节'] }}</strong>
            <span v-if="step['确认人']" class="badge badge-green" style="margin-left:6px">已确认</span>
            <span v-else-if="isFirstEmpty(i)" class="badge badge-blue" style="margin-left:6px">当前待填</span>
            <span v-else class="badge badge-gray" style="margin-left:6px">未开始</span>
            <div class="tl-meta">
              {{ step['执行记录'] || '—' }}
              <span v-if="step['确认人']"> · {{ step['确认人'] }} · {{ step['确认时间'] }}</span>
            </div>
          </li>
        </ul>
        <div v-if="current.status === '执行中'" class="seat-row">
          <input v-model="stepForm.confirmer" placeholder="确认人" style="width:120px" />
          <input v-model="stepForm.record" :placeholder="`填写「${firstEmptyStep?.['环节'] ?? ''}」执行记录`" style="flex:1;min-width:200px" />
          <button class="btn primary" type="button" @click="doConfirmStep">确认本环节</button>
        </div>

        <div v-if="current['完结结论']">
          <h4 class="section-title">{{ current.status === '已回退' ? '回退结论' : '收尾结论' }}（已回写网元台账）</h4>
          <p style="font-size:13px">{{ current['完结结论'] }} <span class="subtle">· {{ current['完结时间'] }}</span></p>
        </div>

        <h4 class="section-title">流转日志</h4>
        <ul class="timeline">
          <li v-for="(log, i) in [...current['流转日志']].reverse()" :key="i">
            <strong>{{ log['环节'] }}</strong>：{{ log['说明'] }}
            <div class="tl-meta">{{ log['时间'] }}</div>
          </li>
        </ul>

        <!-- 动作区 -->
        <div class="modal-foot">
          <span v-if="modalError" class="error-text">{{ modalError }}</span>
          <button v-if="current.status === '立项'" class="btn primary" type="button" @click="doAction('submit-sign')">提交会签</button>
          <button v-if="current.status === '会签未通过'" class="btn" type="button" @click="doAction('resubmit-sign')">按意见改齐，重新提请会签</button>
          <button v-if="current.status === '待执行'" class="btn primary" type="button" @click="doAction('start')">进入执行（从中断/放行处继续）</button>
          <button v-if="current.status === '执行中'" class="btn" type="button" @click="interruptPrompt">中断执行</button>
          <button v-if="current.status === '执行中'" class="btn primary" type="button" @click="finishPrompt(true)">五个环节已齐，收尾完结</button>
          <button v-if="current.status === '待执行' || current.status === '执行中'" class="btn" type="button" @click="finishPrompt(false)">按预案回退</button>
          <button v-if="current.status === '会签未通过' || current.status === '待执行' || current.status === '已回退'"
            class="btn" type="button" @click="showReschedule = true">重新报窗（挪时间）</button>
        </div>

        <!-- 重新报窗 -->
        <div v-if="showReschedule" class="lock-note" style="margin-top:10px">
          窗口锁死不得在原单修改，提交后将以 {{ current['工单号'] }} 为依据新开一单，原单保留原样。
          <div class="seat-row" style="margin-top:8px">
            <input v-model="rescheduleForm['窗口开始']" type="datetime-local" />
            <input v-model="rescheduleForm['窗口结束']" type="datetime-local" />
            <button class="btn primary" type="button" @click="doReschedule">确认重新报窗</button>
          </div>
        </div>
      </div>
    </div>

    <!-- 登记让行作业 -->
    <div v-if="showTask" class="modal-mask" @click.self="showTask = false">
      <div class="modal" style="width:min(560px,96vw)">
        <div class="modal-head"><h3>登记同网元作业（参与让行排程）</h3>
          <button class="modal-close" type="button" @click="showTask = false">×</button></div>
        <form class="form-grid" @submit.prevent="submitTask">
          <label><span>网元编号 *</span><input v-model="taskForm['网元编号']" /></label>
          <label><span>作业类型 *</span>
            <select v-model="taskForm['作业类型']"><option value="巡检">巡检</option><option value="告警处理">告警处理</option></select>
          </label>
          <label><span>作业编号 *</span><input v-model="taskForm['作业编号']" /></label>
          <label><span>提报人</span><input v-model="taskForm['提报人']" /></label>
          <label><span>窗口开始 *</span><input v-model="taskForm['窗口开始']" type="datetime-local" /></label>
          <label><span>窗口结束 *</span><input v-model="taskForm['窗口结束']" type="datetime-local" /></label>
          <label class="full"><span>作业标题 *</span><input v-model="taskForm['作业标题']" /></label>
          <div class="modal-foot full">
            <span v-if="modalError" class="error-text">{{ modalError }}</span>
            <button class="btn primary" type="submit">登记并排程</button>
          </div>
        </form>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'

import { request } from '@/api/client'

type Rec = Record<string, any>

const ENDPOINT = '/api/cutover'
const tabs = [
  { key: 'orders', label: '割接工单' },
  { key: 'schedule', label: '同网元让行排程' },
  { key: 'rejected', label: '重复打回记录' },
] as const

const activeTab = ref<(typeof tabs)[number]['key']>('orders')
const statuses = ['立项', '会签中', '会签未通过', '待执行', '执行中', '已回退', '已完结']
const orderColumns = ['工单号', '所属站点', '网元编号', '变更类型', '变更窗口', '重报来源', '状态']
const statusClassMap: Record<string, string> = {
  立项: 'badge-gray', 会签中: 'badge-blue', 会签未通过: 'badge-red',
  待执行: 'badge-purple', 执行中: 'badge-amber', 已回退: 'badge-red', 已完结: 'badge-green',
}
const primaryAction: Record<string, string> = {
  立项: '提交会签', 会签中: '去会签', 会签未通过: '重新提请/报窗',
  待执行: '进入执行', 执行中: '确认环节', 已回退: '重新报窗', 已完结: '查看',
}

const orders = ref<Rec[]>([])
const orderTotal = ref(0)
const orderFilter = reactive({ keyword: '', status: '', element: '' })
const stats = ref<{ label: string, value: number }[]>([])
const rejected = ref<Rec[]>([])
const scheduleData = ref<Rec>({})

const message = ref('')
const messageOk = ref(false)
const modalError = ref('')
const showCreate = ref(false)
const showTask = ref(false)
const showReschedule = ref(false)
const current = ref<Rec | null>(null)

const blankOrder = (): Rec => ({
  所属站点: '', 网元编号: '', 变更类型: '', 提报人: '',
  窗口开始: '', 窗口结束: '', 变更内容: '', 回退方案: '',
})
const createForm = reactive<Rec>(blankOrder())
const signForm = reactive({ seat: '网络组', result: '通过', signer: '', opinion: '' })
const stepForm = reactive({ confirmer: '', record: '' })
const rescheduleForm = reactive({ 窗口开始: '', 窗口结束: '' })
const taskForm = reactive<Rec>({ 网元编号: '', 作业类型: '巡检', 作业编号: '', 作业标题: '', 提报人: '', 窗口开始: '', 窗口结束: '' })

const availableSeats = computed(() =>
  current.value ? current.value['会签席位'].filter((s: Rec) => !s['结论']).map((s: Rec) => s['席位']) : [])
const firstEmptyStep = computed<Rec | null>(() =>
  current.value ? current.value['执行环节'].find((s: Rec) => !s['确认人']) ?? null : null)

function statusClass(status: string): string {
  return statusClassMap[status] ?? 'badge-gray'
}
function actionLabel(row: Rec): string {
  return primaryAction[String(row.status)] ?? '详情'
}
function isFirstEmpty(index: number): boolean {
  const steps: Rec[] = current.value?.['执行环节'] ?? []
  return steps.findIndex((s) => !s['确认人']) === index
}
function flash(text: string, ok: boolean) {
  message.value = text
  messageOk.value = ok
  setTimeout(() => { message.value = '' }, 4000)
}

async function reloadOrders() {
  const q = new URLSearchParams()
  if (orderFilter.keyword) q.set('keyword', orderFilter.keyword)
  if (orderFilter.status) q.set('status', orderFilter.status)
  if (orderFilter.element) q.set('element', orderFilter.element)
  const resp = await request(`${ENDPOINT}?${q.toString()}`)
  if (!resp.ok) { flash('工单列表读取失败', false); return }
  const data = await resp.json()
  orders.value = data.items ?? []
  orderTotal.value = data.total ?? 0
}
function resetOrderFilter() {
  orderFilter.keyword = ''
  orderFilter.status = ''
  orderFilter.element = ''
  void reloadOrders()
}
async function loadMeta() {
  const resp = await request(`${ENDPOINT}/meta`)
  if (resp.ok) {
    const data = await resp.json()
    stats.value = data.stats ?? []
  }
}
async function loadRejected() {
  const resp = await request(`${ENDPOINT}/rejected`)
  if (resp.ok) rejected.value = (await resp.json()).items ?? []
}
async function loadSchedule() {
  const resp = await request(`${ENDPOINT}/schedule`)
  if (resp.ok) scheduleData.value = await resp.json()
}
async function switchTab(key: string) {
  activeTab.value = key as typeof activeTab.value
  if (key === 'rejected') await loadRejected()
  if (key === 'schedule') await loadSchedule()
}

function openCreate() {
  Object.assign(createForm, blankOrder())
  modalError.value = ''
  showCreate.value = true
}
async function submitCreate() {
  modalError.value = ''
  const resp = await request(ENDPOINT, { method: 'POST', body: JSON.stringify({ values: { ...createForm } }) })
  const data = await resp.json()
  if (!data.ok) { modalError.value = data.message; return }
  showCreate.value = false
  flash(data.message, true)
  await reloadOrders()
  await loadMeta()
}
function openTask() {
  modalError.value = ''
  showTask.value = true
}
async function submitTask() {
  modalError.value = ''
  const resp = await request(`${ENDPOINT}/schedule/tasks`, { method: 'POST', body: JSON.stringify({ values: { ...taskForm } }) })
  const data = await resp.json()
  if (!data.ok) { modalError.value = data.message; return }
  showTask.value = false
  flash(data.message, true)
  await loadSchedule()
}

async function refreshCurrent(id: number) {
  const resp = await request(`${ENDPOINT}/${id}`)
  if (resp.ok) current.value = await resp.json()
}
async function openDetail(row: Rec) {
  modalError.value = ''
  showReschedule.value = false
  await refreshCurrent(Number(row.id))
}
async function openAction(row: Rec) {
  await openDetail(row)
}

async function postAction(path: string, values: Rec = {}): Promise<Rec> {
  const resp = await request(`${ENDPOINT}/${path}`, { method: 'POST', body: JSON.stringify({ values }) })
  return resp.json()
}
async function handleResult(data: Rec, close = false) {
  modalError.value = ''
  if (!data.ok) {
    modalError.value = data.message
    if (current.value) await refreshCurrent(Number(current.value.id))
    return
  }
  flash(data.message, true)
  await loadMeta()
  await reloadOrders()
  if (close) {
    current.value = null
  } else if (data.entry) {
    current.value = data.entry
  }
}

async function doAction(action: string) {
  const id = current.value?.id as number
  const pathMap: Record<string, string> = {
    'submit-sign': `${id}/submit-sign`,
    'resubmit-sign': `${id}/resubmit-sign`,
    start: `${id}/start`,
  }
  const path = pathMap[action]
  if (!path) return
  const data = await postAction(path, {})
  await handleResult(data)
}
async function doCountersign() {
  const id = current.value?.id as number
  const data = await postAction(`${id}/countersign`, { ...signForm })
  signForm.opinion = ''
  signForm.signer = ''
  await handleResult(data)
}
async function doConfirmStep() {
  const id = current.value?.id as number
  const data = await postAction(`${id}/steps/confirm`, { ...stepForm })
  stepForm.confirmer = ''
  stepForm.record = ''
  await handleResult(data)
}
async function interruptPrompt() {
  const reason = window.prompt('中断原因（已确认环节会保留，重新进来从空缺环节继续）', '执行中断')
  if (reason === null) return
  const id = current.value?.id as number
  const data = await postAction(`${id}/interrupt`, { reason })
  await handleResult(data)
}
async function finishPrompt(isFinish: boolean) {
  const label = isFinish ? '收尾结论' : '回退结论'
  const text = window.prompt(`请填写${label}（将回写网元台账）`, isFinish ? '割接成功，业务恢复' : '已按回退方案恢复')
  if (!text) return
  const id = current.value?.id as number
  const data = await postAction(`${id}/${isFinish ? 'finish' : 'rollback'}`, { conclusion: text })
  await handleResult(data, isFinish)
  if (isFinish) await loadSchedule()
}
async function doReschedule() {
  const id = current.value?.id as number
  const resp = await request(`${ENDPOINT}/${id}/reschedule`, {
    method: 'POST',
    body: JSON.stringify({ values: { 窗口开始: rescheduleForm['窗口开始'], 窗口结束: rescheduleForm['窗口结束'] } }),
  })
  const data = await resp.json()
  if (!data.ok) { modalError.value = data.message; return }
  showReschedule.value = false
  current.value = null
  flash(data.message, true)
  await reloadOrders()
  await loadMeta()
}

onMounted(async () => {
  await Promise.all([reloadOrders(), loadMeta()])
})
</script>
