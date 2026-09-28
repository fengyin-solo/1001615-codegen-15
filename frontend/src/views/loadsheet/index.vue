<template>
  <section class="page" data-module="loadsheet">
    <header class="page-head">
      <div>
        <h2>载重平衡管理</h2>
        <p class="page-desc">登记配载单时一并录入计算重量与重心位置，按机型包线上限判限；确认配载、退回重算均记入复核台账，同人复核不予受理。</p>
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

    <div class="tabs">
      <button
        v-for="tab in tabs"
        :key="tab.key"
        class="tab"
        :class="{ active: activeTab === tab.key }"
        type="button"
        @click="switchTab(tab.key)"
      >
        {{ tab.label }}
      </button>
    </div>

    <!-- 配载单列表 -->
    <template v-if="activeTab === 'list'">
      <form class="filter-bar" @submit.prevent="reload">
        <label v-for="field in filterFields" :key="field" class="filter-item">
          <span>{{ field }}</span>
          <input v-model="filters[field]" :placeholder="`按${field}检索`" />
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
              <span v-if="column === '重心合规'" :class="['cg-tag', row['重心合规'] ? 'ok' : 'bad']">
                {{ row['重心合规'] ? '合规' : '超限' }}
              </span>
              <span v-else-if="column === '配载状态'">
                {{ row.status }}
              </span>
              <span v-else>{{ row[column] === '' || row[column] == null ? '—' : row[column] }}</span>
            </td>
            <td class="row-actions">
              <button class="link" type="button" @click="runAction('提交复核', row)">提交复核</button>
              <button
                class="link"
                type="button"
                @click="openReview('确认配载', row)"
              >确认配载</button>
              <button
                class="link danger"
                type="button"
                @click="openReview('退回重算', row)"
              >退回重算</button>
            </td>
          </tr>
          <tr v-if="!rows.length">
            <td :colspan="columns.length + 1" class="empty-state">暂无载重平衡数据，可先登记配载单</td>
          </tr>
        </tbody>
      </table>

      <footer class="page-foot">
        <span>共 {{ total }} 条载重平衡记录 · 计算重量合计 {{ summary['计算重量合计'] ?? '—' }} kg</span>
        <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
      </footer>
    </template>

    <!-- 复核台账 -->
    <template v-else>
      <form class="filter-bar" @submit.prevent="reloadReviews">
        <label class="filter-item">
          <span>配载单号</span>
          <input v-model="reviewFilters.keyword" placeholder="按配载单号检索" />
        </label>
        <label class="filter-item checkbox">
          <input v-model="onlyLatest" type="checkbox" @change="reloadReviews" />
          <span>同一配载单只看最后一次结论</span>
        </label>
        <button class="btn" type="submit">查询</button>
      </form>

      <table class="data-table">
        <thead>
          <tr>
            <th v-for="column in reviewColumns" :key="column">{{ column }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in reviews" :key="String(row.id)">
            <td v-for="column in reviewColumns" :key="column">
              <span v-if="column === '重心合规'" :class="['cg-tag', row['重心合规'] ? 'ok' : 'bad']">
                {{ row['重心合规'] ? '合规' : '超限' }}
              </span>
              <span v-else-if="column === '复核结论'">
                <span :class="['cg-tag', row[column] === '复核通过' ? 'ok' : 'bad']">{{ row[column] }}</span>
              </span>
              <span v-else>{{ row[column] === '' || row[column] == null ? '—' : row[column] }}</span>
            </td>
          </tr>
          <tr v-if="!reviews.length">
            <td :colspan="reviewColumns.length" class="empty-state">暂无复核台账记录</td>
          </tr>
        </tbody>
      </table>

      <footer class="page-foot">
        <span>
          共 {{ reviewTotal }} 条台账记录（{{ summary['复核台账条数'] ?? 0 }} 次送复核） ·
          台账重量合计 {{ summary['台账重量合计'] ?? '—' }} kg ·
          <span :class="summary['台账与列表重量一致'] ? 'ok-text' : 'error-text'">
            {{ summary['台账与列表重量一致'] ? '与列表、汇总同一份数' : '重量口径不一致' }}
          </span>
        </span>
        <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
      </footer>
    </template>

    <!-- 登记配载单 -->
    <div v-if="createOpen" class="modal-mask" @click.self="createOpen = false">
      <div class="modal">
        <h3>登记配载单</h3>
        <p class="modal-tip">计算重量与重心位置随配载单一并录入，重心按机型包线上限判定。</p>
        <div class="form-grid">
          <label v-for="field in createFields" :key="field" class="form-item">
            <span>{{ field }}<em v-if="requiredCreate.includes(field)">*</em></span>
            <input v-model="createForm[field]" :placeholder="field" />
          </label>
          <label class="form-item">
            <span>机型<em>*</em></span>
            <select v-model="createForm['机型']" @change="previewCg">
              <option value="" disabled>请选择机型</option>
              <option v-for="item in envelope" :key="String(item['机型'])" :value="item['机型']">
                {{ item['机型'] }}（包线上限 {{ item['重心上限'] }}{{ item['单位'] }}）
              </option>
            </select>
          </label>
        </div>
        <p v-if="createCgHint" class="cg-hint" :class="createCgOk ? 'ok-text' : 'error-text'">{{ createCgHint }}</p>
        <div class="modal-actions">
          <button class="btn ghost" type="button" @click="createOpen = false">取消</button>
          <button class="btn primary" type="button" @click="submitCreate">登记</button>
        </div>
      </div>
    </div>

    <!-- 复核弹窗：确认配载 / 退回重算 -->
    <div v-if="reviewOpen" class="modal-mask" @click.self="reviewOpen = false">
      <div class="modal">
        <h3>{{ reviewAction }} · {{ reviewRow?.['配载单号'] }}</h3>
        <div class="review-meta">
          <span>机型：{{ reviewRow?.['机型'] }}</span>
          <span>计算重量：{{ reviewRow?.['计算重量'] }} kg</span>
          <span>重心位置：{{ reviewRow?.['重心位置'] }}%MAC</span>
          <span>配载人：{{ reviewRow?.['配载人员'] }}</span>
        </div>
        <p class="cg-hint" :class="reviewRow?.['重心合规'] ? 'ok-text' : 'error-text'">
          {{ reviewRow?.['判限说明'] }}
        </p>
        <div class="form-grid">
          <label class="form-item">
            <span>复核人<em>*</em></span>
            <input v-model="reviewForm['复核人']" placeholder="与配载人同人将不予受理" />
          </label>
          <label class="form-item wide">
            <span>复核意见<em>*</em></span>
            <textarea v-model="reviewForm['复核意见']" rows="3" placeholder="请填写复核意见"></textarea>
          </label>
        </div>
        <div class="modal-actions">
          <button class="btn ghost" type="button" @click="reviewOpen = false">取消</button>
          <button
            class="btn primary"
            :class="{ danger: reviewAction === '退回重算' }"
            type="button"
            @click="submitReview"
          >{{ reviewAction }}</button>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | boolean | null>

const ENDPOINT = '/api/loadsheet'
const columns = ['配载单号', '关联航班', '机型', '计算重量', '重心位置', '重心合规', '油量数据', '配载人员', '复核人员', '复核结论', '配载状态']
const reviewColumns = ['配载单号', '关联航班', '机型', '计算重量', '重心位置', '重心合规', '判限说明', '配载人', '复核人', '复核意见', '复核结论']
const stats = ref([
  { label: '待复核配载', value: 0 },
  { label: '本月配载单数', value: 0 },
  { label: '退回重算数', value: 0 },
  { label: '计算重量合计(kg)', value: 0 },
])

const tabs = [
  { key: 'list', label: '配载单列表' },
  { key: 'ledger', label: '复核台账' },
] as const
type TabKey = (typeof tabs)[number]['key']
const activeTab = ref<TabKey>('list')

const rows = ref<Row[]>([])
const reviews = ref<Row[]>([])
const total = ref(0)
const reviewTotal = ref(0)
const onlyLatest = ref(false)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)
const reviewFilters = reactive({ keyword: '' })
const summary = ref<Record<string, number | boolean | string>>({})
const envelope = ref<Row[]>([])

// ---- 登记配载单 ----
const createOpen = ref(false)
const createFields = ['配载单号', '关联航班', '计算重量', '重心位置', '油量数据', '配载人员']
const requiredCreate = ['配载单号', '关联航班', '计算重量', '重心位置', '配载人员']
const emptyCreate = (): Record<string, string> => ({
  配载单号: '', 关联航班: '', 机型: '', 计算重量: '', 重心位置: '', 油量数据: '', 配载人员: '',
})
const createForm = ref<Record<string, string>>(emptyCreate())
const createCgHint = ref('')
const createCgOk = ref(false)

// ---- 复核 ----
const reviewOpen = ref(false)
const reviewAction = ref('确认配载')
const reviewRow = ref<Row | null>(null)
const reviewForm = reactive({ 复核人: '', 复核意见: '' })

function resetFilters() {
  filters.value = {}
  void reload()
}

function switchTab(key: TabKey) {
  activeTab.value = key
  errorMessage.value = ''
  if (key === 'ledger') void reloadReviews()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  createForm.value = emptyCreate()
  createCgHint.value = ''
  createOpen.value = true
}

async function previewCg() {
  const { 机型, 重心位置 } = createForm.value
  if (!机型 || !重心位置) {
    createCgHint.value = ''
    return
  }
  const limit = Number(envelope.value.find((item) => item['机型'] === 机型)?.['重心上限'])
  const cg = Number(String(重心位置).replace('%', ''))
  if (Number.isNaN(cg)) {
    createCgOk.value = false
    createCgHint.value = '重心位置需为数值'
    return
  }
  createCgOk.value = cg <= limit
  createCgHint.value = createCgOk.value
    ? `重心 ${cg}%MAC 在 ${机型} 包线上限 ${limit}%MAC 以内`
    : `重心 ${cg}%MAC 超出 ${机型} 包线上限 ${limit}%MAC，登记后须退回重算`
}

async function submitCreate() {
  errorMessage.value = ''
  const response = await request(ENDPOINT, {
    method: 'POST',
    body: JSON.stringify({ values: createForm.value }),
  })
  const payload = await response.json()
  if (!payload.ok) {
    errorMessage.value = payload.message ?? '配载单登记失败'
    return
  }
  createOpen.value = false
  await Promise.all([reload(), loadSummary()])
}

function runAction(action: string, row: Row) {
  errorMessage.value = ''
  void doAction(action, row, {})
}

function openReview(action: string, row: Row) {
  reviewAction.value = action
  reviewRow.value = row
  reviewForm.复核人 = ''
  reviewForm.复核意见 = ''
  reviewOpen.value = true
}

async function submitReview() {
  if (!reviewRow.value) return
  await doAction(reviewAction.value, reviewRow.value, {
    复核人: reviewForm.复核人,
    复核意见: reviewForm.复核意见,
  })
}

async function doAction(action: string, row: Row, extra: Record<string, string>) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action, ...extra } }),
    })
    const payload = await response.json()
    if (!payload.ok) {
      errorMessage.value = payload.message ?? '载重平衡动作未生效'
      return
    }
    reviewOpen.value = false
    await Promise.all([reload(), loadSummary()])
    if (activeTab.value === 'ledger') await reloadReviews()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '载重平衡操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) throw new Error('配载单列表读取失败')
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    await loadSummary()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '载重平衡列表读取失败'
  }
}

async function reloadReviews() {
  errorMessage.value = ''
  const params = new URLSearchParams()
  if (reviewFilters.keyword) params.set('keyword', reviewFilters.keyword)
  if (onlyLatest.value) params.set('only_latest', 'true')
  try {
    const response = await request(`${ENDPOINT}/reviews?${params.toString()}`)
    if (!response.ok) throw new Error('复核台账读取失败')
    const payload = await response.json()
    reviews.value = payload.items ?? []
    reviewTotal.value = payload.total ?? reviews.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '复核台账读取失败'
  }
}

async function loadSummary() {
  try {
    const response = await request(`${ENDPOINT}/summary`)
    if (!response.ok) return
    const data = await response.json()
    summary.value = data
    stats.value[0].value = Number(data['待复核数'] ?? 0)
    stats.value[1].value = Number(data['配载单总数'] ?? 0)
    stats.value[2].value = Number(data['退回重算数'] ?? 0)
    stats.value[3].value = Number(data['计算重量合计'] ?? 0)
  } catch {
    // 汇总只是辅助卡片，不阻断列表使用
  }
}

async function loadEnvelope() {
  try {
    const response = await request(`${ENDPOINT}/envelope`)
    if (!response.ok) return
    const data = await response.json()
    envelope.value = data.items ?? []
  } catch {
    // 包线仅用于登记提示，拉不到不阻断
  }
}

onMounted(() => {
  void loadEnvelope()
  void reload()
})
</script>

<style scoped>
.tabs {
  display: flex;
  gap: 8px;
  margin: 12px 0;
}

.tab {
  border: 1px solid var(--border, #d9dce3);
  background: #fff;
  border-radius: 6px;
  padding: 6px 16px;
  cursor: pointer;
}

.tab.active {
  border-color: #2f6bff;
  color: #2f6bff;
  font-weight: 600;
}

.cg-tag {
  display: inline-block;
  padding: 1px 8px;
  border-radius: 10px;
  font-size: 12px;
}

.cg-tag.ok {
  color: #17803d;
  background: #e6f6ec;
}

.cg-tag.bad {
  color: #c02a26;
  background: #fdeaea;
}

.ok-text {
  color: #17803d;
}

.row-actions .link.danger {
  color: #c02a26;
}

.checkbox {
  display: flex;
  align-items: center;
  gap: 6px;
}

.checkbox input {
  width: auto;
}

.modal-mask {
  position: fixed;
  inset: 0;
  background: rgba(20, 24, 32, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 100;
}

.modal {
  width: 560px;
  max-width: calc(100vw - 32px);
  background: #fff;
  border-radius: 10px;
  padding: 20px 24px;
  box-shadow: 0 10px 30px rgba(0, 0, 0, 0.18);
}

.modal h3 {
  margin: 0 0 8px;
}

.modal-tip {
  color: #6b7280;
  font-size: 13px;
  margin: 0 0 12px;
}

.form-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}

.form-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 13px;
}

.form-item.wide {
  grid-column: 1 / -1;
}

.form-item em {
  color: #c02a26;
  font-style: normal;
  margin-left: 2px;
}

.form-item input,
.form-item select,
.form-item textarea {
  padding: 6px 8px;
  border: 1px solid #d9dce3;
  border-radius: 6px;
  font: inherit;
}

.review-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  font-size: 13px;
  color: #374151;
  margin-bottom: 8px;
}

.cg-hint {
  font-size: 13px;
  margin: 10px 0;
}

.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 16px;
}

.btn.danger {
  background: #c02a26;
  border-color: #c02a26;
  color: #fff;
}
</style>
