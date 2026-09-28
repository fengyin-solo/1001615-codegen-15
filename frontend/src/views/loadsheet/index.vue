<template>
  <section class="page" data-module="loadsheet">
    <header class="page-head">
      <div>
        <h2>载重平衡管理</h2>
        <p class="page-desc">
          登记配载单时一并录入计算重量与重心位置，复核按机型重心包线上限判核；
          超限不得直接确认，须退回重算并在复核台账中留痕复核人与意见。
        </p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记配载单</button>
        <button class="btn" type="button" @click="exportRows">导出载重平衡清单</button>
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
        <span>配载单号</span>
        <input v-model="keyword" placeholder="按配载单号检索" />
      </label>
      <label class="filter-item">
        <span>配载状态</span>
        <select v-model="statusFilter">
          <option value="">全部状态</option>
          <option v-for="s in statuses" :key="s" :value="s">{{ s }}</option>
        </select>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">
            <span v-if="column === '重心判定' || column === '最新复核结论'" :class="judgeClass(row[column])">
              {{ row[column] || '—' }}
            </span>
            <span v-else>{{ formatCell(column, row[column]) }}</span>
          </td>
          <td class="row-actions">
            <button class="link" type="button" @click="openReview(row)">提交复核</button>
            <button class="link" type="button" @click="runAction('确认配载', row, {})">确认配载</button>
            <button class="link" type="button" @click="runAction('退回重算', row, {})">退回重算</button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无载重平衡数据，可先登记配载单</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条载重平衡记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <section class="ledger">
      <header class="ledger-head">
        <h3>复核台账</h3>
        <p class="page-desc">同一张配载单重复送复核的，以轮次最大的最后一次结论为准；台账重量取自配载单同一份数据。</p>
      </header>
      <table class="data-table">
        <thead>
          <tr>
            <th v-for="column in reviewColumns" :key="column">{{ column }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in reviews" :key="String(row.id)">
            <td v-for="column in reviewColumns" :key="column">
              <span v-if="column === '复核结论'" :class="judgeClass(row[column])">{{ row[column] }}</span>
              <span v-else>{{ formatCell(column, row[column]) }}</span>
            </td>
          </tr>
          <tr v-if="!reviews.length">
            <td :colspan="reviewColumns.length" class="empty-state">暂无复核记录，提交复核后自动登记台账</td>
          </tr>
        </tbody>
      </table>
    </section>

    <!-- 登记配载单 -->
    <div v-if="createOpen" class="modal-mask" @click.self="createOpen = false">
      <form class="modal" @submit.prevent="submitCreate">
        <h3>登记配载单</h3>
        <label v-for="field in createFields" :key="field" class="modal-item">
          <span>{{ field }}<em v-if="requiredCreate.includes(field)">*</em></span>
          <select v-if="field === '机型'" v-model="createForm[field]">
            <option value="" disabled>请选择机型</option>
            <option v-for="env in envelopes" :key="env.机型" :value="env.机型">
              {{ env.机型 }}（包线上限 {{ env.包线上限 }}%MAC）
            </option>
          </select>
          <input
            v-else
            v-model="createForm[field]"
            :type="field === '计算重量' || field === '重心位置' ? 'number' : 'text'"
            :placeholder="field === '重心位置' ? `%MAC，上限 ${selectedLimit ?? '—'}` : `请输入${field}`"
          />
        </label>
        <p class="modal-hint">重心位置统一以 %MAC 计，超过所选机型包线上限的，复核时将强制退回重算。</p>
        <div class="modal-actions">
          <button class="btn" type="button" @click="createOpen = false">取消</button>
          <button class="btn primary" type="submit">登记</button>
        </div>
      </form>
    </div>

    <!-- 提交复核 -->
    <div v-if="reviewOpen" class="modal-mask" @click.self="reviewOpen = false">
      <form class="modal" @submit.prevent="submitReview">
        <h3>提交复核 · {{ reviewForm.配载单号 }}</h3>
        <p class="modal-hint">
          机型 {{ reviewForm.机型 }}，包线上限 {{ reviewForm.包线上限 }}%MAC，当前判定：
          <span :class="judgeClass(reviewForm.重心判定)">{{ reviewForm.重心判定 }}</span>
        </p>
        <label class="modal-item">
          <span>复核人员<em>*</em></span>
          <input v-model="reviewForm.复核人员" placeholder="不得与配载人员为同一人" />
        </label>
        <label class="modal-item">
          <span>复核意见<em>*</em></span>
          <textarea v-model="reviewForm.复核意见" rows="3" placeholder="通过或退回都须写明意见"></textarea>
        </label>
        <template v-if="reviewForm.配载状态 === '已退回'">
          <p class="modal-hint">该单已退回重算，可将重算后的重量与重心一并提交：</p>
          <label class="modal-item">
            <span>重算计算重量（kg）</span>
            <input v-model="reviewForm.计算重量" type="number" />
          </label>
          <label class="modal-item">
            <span>重算重心位置（%MAC）</span>
            <input v-model="reviewForm.重心位置" type="number" />
          </label>
        </template>
        <div class="modal-actions">
          <button class="btn" type="button" @click="reviewOpen = false">取消</button>
          <button class="btn primary" type="submit">送复核</button>
        </div>
      </form>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>
type Envelope = { 机型: string; 包线上限: number }

const ENDPOINT = '/api/loadsheet'
const columns = ['配载单号', '关联航班', '机型', '计算重量', '重心位置', '包线上限', '重心判定', '油量数据', '配载人员', '复核人员', '复核意见', '最新复核结论', '复核时间', '配载状态']
const reviewColumns = ['配载单号', '机型', '计算重量', '重心位置', '包线上限', '复核结论', '复核人员', '复核意见', '复核时间', '轮次']
const statuses = ['待计算', '待复核', '已确认', '已退回']

const createFields = ['配载单号', '关联航班', '机型', '计算重量', '重心位置', '油量数据', '配载人员']
const requiredCreate = ['配载单号', '关联航班', '机型', '计算重量', '重心位置', '配载人员']

const rows = ref<Row[]>([])
const reviews = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const keyword = ref('')
const statusFilter = ref('')
const envelopes = ref<Envelope[]>([])
const stats = ref([
  { label: '待复核配载', value: '—' },
  { label: '配载单总数', value: '—' },
  { label: '退回重算数', value: '—' },
  { label: '计算重量合计（kg）', value: '—' },
])

const createOpen = ref(false)
const createForm = reactive<Record<string, string | number>>({})
const reviewOpen = ref(false)
const reviewForm = reactive<Record<string, string | number>>({})

const selectedLimit = computed(() =>
  envelopes.value.find((item) => item.机型 === createForm['机型'])?.包线上限 ?? null,
)

function judgeClass(value: unknown) {
  if (value === '合规' || value === '通过') return 'tag tag-ok'
  if (value === '超限' || value === '退回') return 'tag tag-bad'
  return ''
}

function formatCell(column: string, value: unknown) {
  if (value === null || value === undefined || value === '') return '—'
  if (column === '重心位置' || column === '包线上限') return `${value}%MAC`
  return String(value)
}

function resetFilters() {
  keyword.value = ''
  statusFilter.value = ''
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  for (const field of createFields) createForm[field] = ''
  createOpen.value = true
  errorMessage.value = ''
}

function openReview(row: Row) {
  Object.assign(reviewForm, {
    id: row.id,
    配载单号: row['配载单号'],
    机型: row['机型'],
    包线上限: row['包线上限'],
    重心判定: row['重心判定'],
    配载状态: row['配载状态'],
    复核人员: '',
    复核意见: '',
    计算重量: row['计算重量'] ?? '',
    重心位置: row['重心位置'] ?? '',
  })
  reviewOpen.value = true
  errorMessage.value = ''
}

async function submitCreate() {
  errorMessage.value = ''
  try {
    const response = await request(ENDPOINT, {
      method: 'POST',
      body: JSON.stringify({ values: { ...createForm } }),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) {
      throw new Error(payload.message || '配载单登记失败')
    }
    createOpen.value = false
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '配载单登记失败'
  }
}

async function submitReview() {
  const values: Record<string, string | number> = {
    复核人员: reviewForm['复核人员'],
    复核意见: reviewForm['复核意见'],
  }
  if (reviewForm['配载状态'] === '已退回') {
    values['计算重量'] = reviewForm['计算重量']
    values['重心位置'] = reviewForm['重心位置']
  }
  await runAction('提交复核', { id: reviewForm.id } as Row, values)
  if (!errorMessage.value) reviewOpen.value = false
}

async function runAction(action: string, row: Row, extra: Record<string, string | number>) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action, ...extra } }),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) {
      throw new Error(payload.message || '载重平衡动作未生效，请稍后重试')
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '载重平衡操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams()
  if (keyword.value) query.set('keyword', keyword.value)
  if (statusFilter.value) query.set('status', statusFilter.value)
  try {
    const [listResp, reviewResp, summaryResp] = await Promise.all([
      request(`${ENDPOINT}?${query.toString()}`),
      request(`${ENDPOINT}/reviews`),
      request(`${ENDPOINT}/summary`),
    ])
    if (!listResp.ok) throw new Error('配载单列表读取失败')
    const payload = await listResp.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    if (reviewResp.ok) {
      const reviewPayload = await reviewResp.json()
      reviews.value = reviewPayload.items ?? []
    }
    if (summaryResp.ok) {
      const summary = await summaryResp.json()
      envelopes.value = summary['机型包线'] ?? []
      stats.value = [
        { label: '待复核配载', value: summary['待复核配载'] },
        { label: '配载单总数', value: summary['配载单总数'] },
        { label: '退回重算数', value: summary['退回重算数'] },
        { label: '计算重量合计（kg）', value: Number(summary['计算重量合计']).toLocaleString() },
      ]
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '载重平衡列表读取失败'
  }
}

onMounted(reload)
</script>

<style scoped>
.ledger {
  margin-top: 20px;
}
.ledger-head h3 {
  margin: 0 0 4px;
  font-size: 15px;
}
.modal-mask {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 20;
}
.modal {
  width: 460px;
  max-height: 86vh;
  overflow-y: auto;
  background: #fff;
  border-radius: 10px;
  padding: 18px 20px;
}
.modal h3 {
  margin: 0 0 12px;
}
.modal-item {
  display: block;
  margin-bottom: 10px;
}
.modal-item span {
  display: block;
  font-size: 12px;
  color: var(--muted);
  margin-bottom: 4px;
}
.modal-item em {
  color: #b42318;
  font-style: normal;
  margin-left: 2px;
}
.modal-item input,
.modal-item select,
.modal-item textarea {
  width: 100%;
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 6px 8px;
  font: inherit;
}
.modal-hint {
  font-size: 12px;
  color: var(--muted);
  margin: 4px 0 12px;
}
.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}
.tag {
  display: inline-block;
  padding: 1px 8px;
  border-radius: 10px;
  font-size: 12px;
}
.tag-ok {
  background: #e7f6ec;
  color: #1d7a3f;
}
.tag-bad {
  background: #fdecec;
  color: #b42318;
}
</style>
