const API_BASE = '/api/v1'

function getToken(): string | null {
  return localStorage.getItem('token')
}

function authHeaders(): Record<string, string> {
  const token = getToken()
  return token ? { Authorization: `Bearer ${token}` } : {}
}

function handleUnauthorized(status: number) {
  if (status !== 401) return
  clearAuth()
  if (window.location.pathname !== '/login') window.location.href = '/login'
}

export function genIdempotencyKey(): string {
  if (typeof crypto !== 'undefined' && crypto.randomUUID) return crypto.randomUUID()
  return `${Date.now()}-${Math.random().toString(36).slice(2)}`
}

export function getUser(): { username: string; role: string; display_name: string } | null {
  const raw = localStorage.getItem('user')
  return raw ? JSON.parse(raw) : null
}

export function setAuth(token: string, user: object) {
  localStorage.setItem('token', token)
  localStorage.setItem('user', JSON.stringify(user))
}

export function clearAuth() {
  localStorage.removeItem('token')
  localStorage.removeItem('user')
}

export async function api(
  path: string,
  opts: { method?: string; body?: object; idempotency?: boolean } = {},
): Promise<any> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  const token = getToken()
  if (token) headers['Authorization'] = `Bearer ${token}`
  if (opts.idempotency) headers['X-Idempotency-Key'] = genIdempotencyKey()

  const res = await fetch(`${API_BASE}${path}`, {
    method: opts.method || 'GET',
    headers,
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  })
  if (res.status === 401) {
    handleUnauthorized(res.status)
    throw new Error('未登录或登录已过期')
  }
  const data = await res.json().catch(() => ({}))
  if (!res.ok) {
    const msg = data?.error?.message || data?.detail || `请求失败 (${res.status})`
    throw new Error(msg)
  }
  return data
}

export async function login(username: string, password: string) {
  return api('/auth/login', { method: 'POST', body: { username, password } })
}

export interface CaseListItem {
  case_id: string
  order_id: string
  amount_yuan: string
  status: string
  risk_level: string | null
  decision: string | null
  refund_status: string | null
  created_at: string | null
}

// ---------------- 工作台统计 ----------------

export interface StatsBucket {
  total: number
  completed: number
  rejected: number
  suspended: number
  failed: number
  running: number
  auto_approved: number
  auto_rate: number
  avg_duration_seconds: number
  total_amount_cent: number
  total_amount_yuan: number
}

export interface StatsTrendItem {
  date: string
  total: number
  completed: number
  rejected: number
  suspended: number
}

export interface StatsOverview {
  today: StatsBucket
  overall: StatsBucket
  trend: StatsTrendItem[]
  status_distribution: Record<string, number>
  risk_distribution: Record<string, number>
}

export async function getStatsOverview(): Promise<StatsOverview> {
  return api('/stats/overview')
}

export interface AgentRun {
  agent_name: string
  status: string
  output_summary: string | null
  error: string | null
  started_at: string | null
  finished_at: string | null
}

export interface CaseDetail {
  case_id: string
  order_id: string
  source?: string
  amount_cent: number
  amount_yuan: string
  currency: string
  status: string
  version: number
  decision: string | null
  decision_reason: string | null
  risk_level: string | null
  fraud_score: number | null
  sentiment_score: number | null
  ocr_confidence: number | null
  risk_flags: Record<string, any> | null
  complaint_text: string
  review_comment: string | null
  refund_status: string | null
  refund_ref: string | null
  trace_id: string
  created_at: string | null
  updated_at: string | null
  agent_runs: AgentRun[]
  evidences: { file_name: string; evidence_id: number; ocr_text: string | null; ocr_confidence: number | null; ocr_corrected: boolean }[]
  risk: { fraud_score: number; sentiment_score: number; risk_level: string; risk_factors: any } | null
  review_task: { id: number; assigned_to: string | null; status: string; comment: string | null } | null
  // 用户长期退款画像（反薅羊毛）
  refund_rate: number | null
  applicant: {
    user_id: number
    username: string
    display_name: string
    total_cases: number
    refund_count: number
    refund_rate: number
  } | null
  // 订单真实性校验
  is_verified_order: boolean | null
  order_verify_error: string | null
  verified_order_amount: number | null
  // 商品一致性校验
  product_match: boolean | null
  claimed_product: string | null
  purchased_product: string | null
  product_consistency_risk: string | null
}

export async function listCases(status?: string): Promise<{ total: number; items: CaseListItem[] }> {
  const q = status ? `?status=${encodeURIComponent(status)}` : ''
  return api(`/cases${q}`)
}

export async function getCase(caseId: string): Promise<CaseDetail> {
  return api(`/cases/${caseId}`)
}

// ---------------- Langfuse 观测 ----------------

export interface TraceSpan {
  span_id: string
  parent_id: string | null
  span_type: string
  name: string
  start_time: number
  end_time: number | null
  duration_ms: number
  error: string | null
  input: string
  output: string
}

export interface CaseTrace {
  trace_id: string
  backend: 'langfuse' | 'file'
  available: boolean
  langfuse_url?: string
  name?: string
  start_time?: number
  end_time?: number | null
  duration_ms?: number
  error?: string | null
  spans: TraceSpan[]
}

export async function getCaseTrace(caseId: string): Promise<CaseTrace> {
  return api(`/cases/${caseId}/trace`)
}

export interface UploadEvidenceResult {
  file_name: string
  file_path: string
  mime_type: string
  file_size: number
  ocr_text?: string | null
  ocr_confidence?: number | null
  ocr_fields?: {
    amount?: number
    date?: string
    order_id?: string
    [key: string]: any
  } | null
}

export async function uploadEvidence(file: File): Promise<UploadEvidenceResult> {
  const token = getToken()
  const body = new FormData()
  body.append('file', file)
  const res = await fetch(`${API_BASE}/cases/upload`, {
    method: 'POST',
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    body,
  })
  if (res.status === 401) {
    handleUnauthorized(res.status)
    throw new Error('未登录或登录已过期')
  }
  const data = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error(data?.error?.message || data?.detail || `上传失败 (${res.status})`)
  return data
}

export async function createCase(body: {
  order_id: string
  amount_cent: number
  currency?: string
  complaint_text?: string
  risk_flags?: Record<string, any>
  evidence?: { file_name: string; file_hash?: string }[]
}): Promise<{ case_id: string; status: string }> {
  return api('/cases', { method: 'POST', body, idempotency: true })
}

export async function decideCase(
  caseId: string,
  body: { action: 'APPROVE' | 'REJECT'; comment?: string },
): Promise<{ case_id: string; status: string; action: string }> {
  return api(`/cases/${caseId}/decision`, { method: 'POST', body, idempotency: true })
}

export interface ReviewTaskItem {
  task: {
    id: number
    case_id: string
    assigned_to: string | null
    status: string
    comment: string | null
    created_at: string | null
    escalated: boolean
    review_reason: string | null
    refund_guard: {
      amount_yuan: string | null
      recommended_amount_yuan: string | null
      partial_refund: boolean
      ocr_amount_mismatch: boolean
      ocr_order_mismatch: boolean
      abuse_signal_count: number
    }
    applicant: {
      user_id: number
      username: string
      display_name: string
      total_cases: number
      refund_count: number
      refund_rate: number
    } | null
  }
}

export async function listReviewTasks(): Promise<ReviewTaskItem[]> {
  return api('/review-tasks')
}

export interface BatchApprovalResult {
  total: number
  approved: number
  rejected: number
  failed: number
  failures: { case_id: string; error: string }[]
}

export async function downloadBatchApprovals(): Promise<number> {
  const res = await fetch(`${API_BASE}/batch/export`, { headers: authHeaders() })
  handleUnauthorized(res.status)
  if (!res.ok) {
    const data = await res.json().catch(() => ({}))
    throw new Error(data?.detail || `导出失败 (${res.status})`)
  }

  const blob = await res.blob()
  const disposition = res.headers.get('Content-Disposition') || ''
  const matched = disposition.match(/filename="?([^";]+)"?/i)
  const filename = matched?.[1] || 'suspended_cases.xlsx'
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(url)
  return Number(res.headers.get('X-Total-Count') || 0)
}

export async function uploadBatchApprovals(file: File): Promise<BatchApprovalResult> {
  const body = new FormData()
  body.append('file', file)
  const res = await fetch(`${API_BASE}/batch/upload`, {
    method: 'POST',
    headers: authHeaders(),
    body,
  })
  handleUnauthorized(res.status)
  const data = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error(data?.detail || `上传失败 (${res.status})`)
  return data
}

// ---------------- 管理员接口 ----------------

export interface Thresholds {
  amount_human_review_threshold_cent: number
  ocr_confidence_threshold: number
  fraud_reject_threshold: number
  fraud_review_threshold: number
  // 安全配置（工单6）
  tool_filter_amount_max: number
  critic_rule_enabled: boolean
  critic_llm_enabled: boolean
  dlp_enabled: boolean
  // 价格偏差阈值
  price_deviation_threshold_cent: number
  // 用户长期退款率阈值（与本次高比例申请组合判断）
  refund_rate_review_threshold: number
  refund_rate_reject_threshold: number
}

export async function getThresholds(): Promise<Thresholds> {
  return api('/admin/thresholds')
}

export async function updateThresholds(body: Partial<Thresholds>): Promise<Thresholds> {
  return api('/admin/thresholds', { method: 'PUT', body })
}

export interface AdminUser {
  id: number
  username: string
  role: string
  display_name: string
  is_active: boolean
  created_at: string | null
}

export async function listUsers(): Promise<AdminUser[]> {
  return api('/admin/users')
}

export async function createUser(body: {
  username: string
  password: string
  role: string
  display_name?: string
}): Promise<AdminUser> {
  return api('/admin/users', { method: 'POST', body })
}

export async function updateUser(
  id: number,
  body: { role?: string; display_name?: string; is_active?: boolean; password?: string },
): Promise<AdminUser> {
  return api(`/admin/users/${id}`, { method: 'PATCH', body })
}

export interface AuditLogItem {
  id: number
  case_id: string | null
  actor_id: number | null
  actor_username: string | null
  action: string
  before_value: any
  after_value: any
  created_at: string | null
}

export async function listAuditLogs(params: {
  case_id?: string
  actor_id?: number
  action?: string
  limit?: number
  offset?: number
} = {}): Promise<{ total: number; items: AuditLogItem[] }> {
  const q = new URLSearchParams()
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== '') q.set(k, String(v))
  })
  const qs = q.toString()
  return api(`/admin/audit-logs${qs ? `?${qs}` : ''}`)
}

export interface HealthStatus {
  status: string
  version: string
  checks: { database: { status: string; latency_ms?: number; error?: string }; redis: { status: string; latency_ms?: number; error?: string } }
}

export async function getHealth(): Promise<HealthStatus> {
  return api('/health')
}

// ---------------- 顾客端：商城、订单、退款、智能客服 ----------------

export interface CustomerProduct {
  id: number
  product_code: string
  name: string
  main_category: string
  main_category_label: string
  sub_category: string
  sub_category_label: string
  color: string
  sizes: string[]
  price_cent: number
  price_yuan: string
  image_url: string | null
  fabric: string | null
  fit_notes: string | null
  description: string | null
  is_demo: boolean
}

export interface CustomerOrderItem {
  id: number
  product_id: number
  name: string
  sub_category: string
  sub_category_label: string
  size: string
  color: string
  quantity: number
  unit_price_cent: number
  unit_price_yuan: string
  line_total_cent?: number
  line_total_yuan?: string
  image_url?: string | null
  refundable_cent?: number
  refundable_yuan?: string
  has_active_refund?: boolean
}

export interface CustomerOrder {
  id: number
  order_no: string
  status: string
  status_label: string
  total_cent: number
  total_yuan: string
  created_at: string | null
  items: CustomerOrderItem[]
  refundable_cent?: number
  refundable_yuan?: string
  refunded_yuan?: string
  has_active_refund?: boolean
  pricing?: {
    subtotal_cent: number
    subtotal_yuan: string
    discount_cent: number
    discount_yuan: string
    freight_cent: number
    freight_yuan: string
    paid_cent: number
    paid_yuan: string
  }
  payment?: {
    payment_no: string
    method: string
    status: string
    status_label: string
    is_demo: boolean
  }
  recipient?: {
    name: string
    phone: string
    address: string
    is_demo: boolean
  }
  logistics?: {
    carrier: string
    tracking_no: string
    status_label: string
    current: number
    steps: { title: string; description: string; state: 'finish' | 'process' | 'wait' }[]
    is_demo: boolean
  }
}

export interface CustomerRefund {
  case_id: string
  order_no: string
  product_name: string | null
  sub_category: string | null
  amount_cent: number
  amount_yuan: string
  partial_refund?: boolean
  recommended_amount_cent?: number | null
  recommended_amount_yuan?: string | null
  issue_severity?: 'minor' | 'moderate' | 'severe' | null
  issue_severity_label?: string | null
  status: string
  friendly_status: string
  created_at: string | null
}

export interface CustomerRefundDetail extends CustomerRefund {
  product_id: number | null
  order_item_id: number | null
  reason: string
  description: string
  updated_at: string | null
  refund_status: string | null
  refund_ref: string | null
  amount_explanation?: string
  timeline: {
    key: string
    title: string
    description: string
    state: 'finish' | 'process' | 'wait' | 'error'
    at: string | null
  }[]
  evidence: { evidence_id: number; file_name: string; uploaded_at: string | null }[]
  friendly_explanation: string
}

export interface CustomerUpload {
  file_name: string
  file_hash: string
  file_path: string
  mime_type: string
  file_size: number
  ocr_text?: string | null
  ocr_confidence?: number | null
  ocr_fields?: Record<string, unknown> | null
  ocr_amount_match?: boolean | null
}

export interface CustomerRefundQuote {
  refundable_cent: number
  refundable_yuan: string
  recommended_amount_cent: number
  recommended_amount_yuan: string
  recommended_rate: number
  issue_severity: 'minor' | 'moderate' | 'severe'
  issue_severity_label: string
  is_partial: boolean
  explanation: string
}

export interface AssistantResultItem {
  kind: 'product' | 'order' | 'refund'
  title: string
  url: string
  product_id?: number
  product_code?: string
  name?: string
  main_category?: string
  sub_category?: string
  color?: string
  fabric?: string
  fit_notes?: string
  price_yuan?: string
  image_url?: string | null
  match_reason?: string
  order_no?: string
  status?: string
  status_label?: string
  payment_status_label?: string
  total_yuan?: string
  created_at?: string | null
  items?: { name: string; size: string; color: string; quantity: number }[]
  case_id?: string
  product_name?: string | null
  amount_yuan?: string
}

export interface AssistantReply {
  session_id: string
  input_source: 'text' | 'voice'
  intents: string[]
  entities: Record<string, unknown>
  confidence: number
  answer: string
  citations: string[]
  retrieved: { doc_key: string; title: string; version: string; score: number }[]
  action: string | null
  data: AssistantResultItem[] | null
  generator: string
}

export async function listCustomerProducts(params: {
  mainCategory?: string
  subCategory?: string
  query?: string
  pageSize?: number
} = {}): Promise<{ total: number; items: CustomerProduct[] }> {
  const q = new URLSearchParams()
  if (params.mainCategory) q.set('main_category', params.mainCategory)
  if (params.subCategory) q.set('sub_category', params.subCategory)
  if (params.query) q.set('q', params.query)
  q.set('page_size', String(params.pageSize || 96))
  return api(`/customer/products?${q.toString()}`)
}

export async function createCustomerOrder(
  items: { product_id: number; size: string; color?: string; quantity: number }[],
): Promise<CustomerOrder> {
  return api('/customer/orders', { method: 'POST', body: { items } })
}

export async function listCustomerOrders(): Promise<CustomerOrder[]> {
  return api('/customer/orders')
}

export async function getCustomerOrder(orderNo: string): Promise<CustomerOrder> {
  return api(`/customer/orders/${encodeURIComponent(orderNo)}`)
}

export async function listCustomerRefunds(): Promise<CustomerRefund[]> {
  return api('/customer/refunds')
}

export async function getCustomerRefund(caseId: string): Promise<CustomerRefundDetail> {
  return api(`/customer/refunds/${encodeURIComponent(caseId)}`)
}

export async function createCustomerRefund(
  orderNo: string,
  body: {
    item_id?: number
    amount_cent?: number
    reason_code: string
    issue_severity?: 'minor' | 'moderate' | 'severe'
    description?: string
    evidence?: { file_name: string; file_hash?: string; file_path: string }[]
  },
): Promise<{ case_id: string; status: string; friendly_status: string }> {
  return api(`/customer/orders/${encodeURIComponent(orderNo)}/refund`, {
    method: 'POST',
    body,
    idempotency: true,
  })
}

export async function getCustomerRefundQuote(
  orderNo: string,
  itemId: number,
  reasonCode: string,
  issueSeverity: 'minor' | 'moderate' | 'severe',
): Promise<CustomerRefundQuote> {
  const query = new URLSearchParams({
    item_id: String(itemId),
    reason_code: reasonCode,
    issue_severity: issueSeverity,
  })
  return api(`/customer/orders/${encodeURIComponent(orderNo)}/refund-quote?${query}`)
}

export async function uploadCustomerEvidence(file: File, amountCent?: number): Promise<CustomerUpload> {
  const body = new FormData()
  body.append('file', file)
  const query = amountCent && amountCent > 0 ? `?amount_cent=${amountCent}` : ''
  const res = await fetch(`${API_BASE}/customer/uploads${query}`, {
    method: 'POST',
    headers: authHeaders(),
    body,
  })
  handleUnauthorized(res.status)
  const data = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error(data?.error?.message || data?.detail || `上传失败 (${res.status})`)
  return data
}

export async function askAssistant(
  text: string,
  sessionId?: string,
  inputSource: 'text' | 'voice' = 'text',
  useModelFallback = false,
): Promise<AssistantReply> {
  return api('/customer/assistant', {
    method: 'POST',
    body: { text, session_id: sessionId, input_source: inputSource, use_model_fallback: useModelFallback },
  })
}

export async function transcribeVoice(file: Blob): Promise<{ text: string; provider: string; demo: boolean }> {
  const body = new FormData()
  body.append('file', file, 'voice.webm')
  const res = await fetch(`${API_BASE}/customer/voice/transcribe`, {
    method: 'POST',
    headers: authHeaders(),
    body,
  })
  handleUnauthorized(res.status)
  const data = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error(data?.error?.message || data?.detail || `语音识别失败 (${res.status})`)
  return data
}
