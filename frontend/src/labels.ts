export const STATUS_META: Record<string, { text: string; color: string }> = {
  CREATED: { text: '已创建', color: 'default' },
  RUNNING: { text: '处理中', color: 'processing' },
  SUSPENDED: { text: '待人工审批', color: 'warning' },
  APPROVED: { text: '已批准', color: 'processing' },
  COMPLETED: { text: '已完成', color: 'success' },
  REJECTED: { text: '已驳回', color: 'error' },
  FAILED: { text: '失败', color: 'error' },
}

export const RISK_META: Record<string, { text: string; color: string }> = {
  HIGH: { text: '高风险', color: 'red' },
  MEDIUM: { text: '中风险', color: 'orange' },
  LOW: { text: '低风险', color: 'green' },
}

export function statusMeta(status: string) {
  return STATUS_META[status] || { text: status, color: 'default' }
}

export function riskMeta(level: string | null | undefined) {
  if (!level) return { text: '—', color: 'default' }
  return RISK_META[level] || { text: level, color: 'default' }
}
