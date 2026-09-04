import { useCallback, useEffect, useState } from 'react'
import {
  Alert,
  Button,
  Card,
  Col,
  Descriptions,
  Empty,
  Form,
  Input,
  List,
  Modal,
  Row,
  Space,
  Tag,
  Timeline,
  Typography,
  message,
} from 'antd'
import { CheckCircleOutlined, CloseCircleOutlined, EditOutlined, ExportOutlined, MinusCircleOutlined } from '@ant-design/icons'
import { useParams } from 'react-router-dom'
import AppLayout from '../components/AppLayout'
import AgentFlow from '../components/AgentFlow'
import { api, decideCase, getCase, getCaseTrace, getUser, type CaseDetail, type CaseTrace } from '../api'
import { riskMeta, statusMeta } from '../labels'

const SPAN_TITLE: Record<string, string> = {
  intake: '受理校验',
  order_verify: '订单校验',
  product_consistency: '商品一致性',
  critic: '注入拦截',
  evidence: '取证(OCR)',
  fraud: '欺诈检测',
  sentiment: '舆情检测',
  merged_risk: '风险评分',
  decision: '决策',
  human_review: '人工审批',
  execute_refund: '退款执行',
  reject: '驳回',
}

/** Langfuse Trace 观测卡片：Span 瀑布图 + 输入输出预览（主管/管理员可见） */
function TraceCard({ trace }: { trace: CaseTrace | null }) {
  if (!trace) {
    return (
      <Card title="LLM 观测（Langfuse Trace）" size="small">
        <Card loading style={{ border: 'none' }} />
      </Card>
    )
  }

  const backendTag =
    trace.backend === 'langfuse' ? (
      <Tag color="purple">Langfuse 云端</Tag>
    ) : (
      <Tag>本地文件降级（未配置 Langfuse Key）</Tag>
    )

  if (!trace.available || !trace.spans?.length) {
    return (
      <Card title="LLM 观测（Langfuse Trace）" size="small" extra={backendTag}>
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description={
            <span style={{ fontSize: 12 }}>
              暂无 Trace 数据：案件处理完成（或审批通过）后生成，旧案件无埋点。
            </span>
          }
        />
      </Card>
    )
  }

  const spans = [...trace.spans].sort((a, b) => a.start_time - b.start_time)
  const t0 = trace.start_time ?? spans[0].start_time
  const totalMs = Math.max(trace.duration_ms ?? 0, 1)
  const llmCount = spans.filter((s) => s.span_type === 'llm').length
  const errCount = spans.filter((s) => s.error).length

  return (
    <Card
      title="LLM 观测（Langfuse Trace）"
      size="small"
      extra={
        <Space>
          {backendTag}
          {trace.langfuse_url && (
            <Button
              size="small"
              type="link"
              icon={<ExportOutlined />}
              href={trace.langfuse_url}
              target="_blank"
            >
              在 Langfuse 打开
            </Button>
          )}
        </Space>
      }
    >
      <Space wrap size={[16, 4]} style={{ marginBottom: 12 }}>
        <Typography.Text>
          总耗时 <b>{(totalMs / 1000).toFixed(2)}s</b>
        </Typography.Text>
        <Typography.Text>
          Span 数 <b>{spans.length}</b>
        </Typography.Text>
        <Typography.Text>
          LLM 调用 <b>{llmCount}</b> 次
        </Typography.Text>
        {errCount > 0 && <Tag color="red">异常 {errCount}</Tag>}
        {trace.error && <Tag color="red">Trace 错误</Tag>}
      </Space>

      {/* Span 瀑布图：按相对起点定位耗时条（紫=LLM 调用，蓝=工具节点，红=异常） */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        {spans.map((s) => {
          const left = Math.min(((s.start_time - t0) * 1000) / totalMs * 100, 100)
          const width = Math.max((s.duration_ms / totalMs) * 100, 1.5)
          const isLlm = s.span_type === 'llm'
          const barColor = s.error ? '#ff4d4f' : isLlm ? '#722ed1' : '#1677ff'
          return (
            <div key={s.span_id} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{ width: 110, fontSize: 12, textAlign: 'right', flexShrink: 0 }} title={s.name}>
                {SPAN_TITLE[s.name] || s.name}
              </span>
              {isLlm && <Tag color="purple" style={{ marginRight: 0, lineHeight: '16px' }}>LLM</Tag>}
              <div
                style={{
                  flex: 1,
                  height: 18,
                  background: '#f5f5f5',
                  borderRadius: 3,
                  position: 'relative',
                  overflow: 'hidden',
                }}
                title={`${s.name}：${s.duration_ms.toFixed(1)}ms${s.error ? `（${s.error}）` : ''}`}
              >
                <div
                  style={{
                    position: 'absolute',
                    left: `${left}%`,
                    width: `${width}%`,
                    top: 0,
                    bottom: 0,
                    background: barColor,
                    borderRadius: 3,
                    opacity: 0.85,
                  }}
                />
              </div>
              <span style={{ width: 74, fontSize: 12, color: '#888', flexShrink: 0 }}>
                {s.duration_ms >= 1000 ? `${(s.duration_ms / 1000).toFixed(2)}s` : `${s.duration_ms.toFixed(0)}ms`}
              </span>
            </div>
          )
        })}
      </div>

      {/* 输入/输出预览（完整数据在 Langfuse 云端或 logs/traces/） */}
      <Typography.Paragraph type="secondary" style={{ fontSize: 12, marginTop: 12, marginBottom: 4 }}>
        Span 输入 / 输出（截断至 500 字符）：
      </Typography.Paragraph>
      {spans.map((s) => (
        <Typography.Paragraph
          key={`io-${s.span_id}`}
          style={{ marginBottom: 4, fontSize: 12, whiteSpace: 'pre-wrap' }}
        >
          <Tag color={s.error ? 'red' : 'blue'} style={{ marginRight: 6 }}>
            {SPAN_TITLE[s.name] || s.name}
          </Tag>
          {s.error ? <Tag color="red">error</Tag> : null}
          <Typography.Text
            type="secondary"
            ellipsis={{ tooltip: `in: ${s.input || '—'}  out: ${s.output || '—'}` }}
            style={{ fontSize: 12, display: 'inline-block', maxWidth: '100%' }}
          >
            {`in: ${s.input || '—'}  out: ${s.output || '—'}`}
          </Typography.Text>
        </Typography.Paragraph>
      ))}
    </Card>
  )
}

export default function CaseDetail() {
  const { caseId = '' } = useParams()
  const [detail, setDetail] = useState<CaseDetail | null>(null)
  const [comment, setComment] = useState('')
  const [acting, setActing] = useState(false)
  const user = getUser()

  const load = useCallback(async () => {
    try {
      const d = await getCase(caseId)
      setDetail(d)
    } catch (e: any) {
      message.error(e.message)
    }
  }, [caseId])

  useEffect(() => {
    load()
    const t = setInterval(load, 3000)
    return () => clearInterval(t)
  }, [load])

  // ---- OCR 修正弹窗（hooks 必须放在所有提前 return 之前，保持渲染顺序稳定）----
  const [ocrModalOpen, setOcrModalOpen] = useState(false)
  const [ocrEditing, setOcrEditing] = useState<{ evidenceId: number; fileName: string; originalText: string } | null>(null)
  const [ocrForm] = Form.useForm()
  const [ocrSubmitting, setOcrSubmitting] = useState(false)

  // ---- Langfuse Trace：仅主管/管理员可见；案件状态变化（终态/挂起）时刷新 ----
  const [trace, setTrace] = useState<CaseTrace | null>(null)
  const canViewTrace = !!user && ['supervisor', 'admin'].includes(user.role)
  const statusKey = detail?.status ?? ''
  useEffect(() => {
    if (!canViewTrace || !caseId) return
    let cancelled = false
    getCaseTrace(caseId)
      .then((t) => {
        if (!cancelled) setTrace(t)
      })
      .catch(() => {}) // 404/旧案件无 trace 时静默，卡片内已有空态
    return () => {
      cancelled = true
    }
  }, [caseId, statusKey, canViewTrace])

  if (!detail) return <AppLayout><Card loading /></AppLayout>

  const isSuspended = detail.status === 'SUSPENDED'
  const canDecide = isSuspended && user && ['supervisor', 'admin'].includes(user.role)
  const canEditOcr = isSuspended && user && ['supervisor', 'admin'].includes(user.role)

  const openOcrEditor = (ev: { evidence_id: number; file_name: string; ocr_text: string | null }) => {
    setOcrEditing({ evidenceId: ev.evidence_id, fileName: ev.file_name, originalText: ev.ocr_text || '' })
    ocrForm.setFieldsValue({ corrected_text: ev.ocr_text || '' })
    setOcrModalOpen(true)
  }

  const submitOcrCorrection = async () => {
    if (!ocrEditing) return
    const values = await ocrForm.validateFields()
    setOcrSubmitting(true)
    try {
      await api(`/cases/${caseId}/evidence/${ocrEditing.evidenceId}/ocr`, {
        method: 'PUT',
        body: { ocr_text: values.corrected_text, ocr_confidence: 1.0 },
      })
      message.success('OCR 修正已保存')
      setOcrModalOpen(false)
      await load()
    } catch (e: any) {
      message.error(e.message)
    } finally {
      setOcrSubmitting(false)
    }
  }

  const decide = async (action: 'APPROVE' | 'REJECT') => {
    setActing(true)
    try {
      await decideCase(caseId, { action, comment: comment || undefined })
      message.success(action === 'APPROVE' ? '已批准，退款执行中' : '已驳回')
      setComment('')
      await load()
    } catch (e: any) {
      message.error(e.message)
    } finally {
      setActing(false)
    }
  }

  const sm = statusMeta(detail.status)
  const rm = riskMeta(detail.risk_level)
  const refundGuard = detail.risk_flags || {}
  const abuseSignals = [
    refundGuard.cross_account_evidence_reuse && '凭证跨账号复用',
    refundGuard.duplicate_evidence && '重复使用凭证',
    refundGuard.refund_velocity_24h && '24小时高频申请',
    refundGuard.refund_velocity_7d && '7天高频申请',
    refundGuard.repeated_high_ratio && '连续高比例退款',
  ].filter(Boolean) as string[]

  const orderVerified = detail.is_verified_order
  const orderVerifyBadge = orderVerified === true
    ? <Tag icon={<CheckCircleOutlined />} color="success">已验证</Tag>
    : orderVerified === false
    ? <Tag icon={<CloseCircleOutlined />} color="error">未通过</Tag>
    : <Tag icon={<MinusCircleOutlined />} color="default">未校验</Tag>

  const productMatch = detail.product_match
  const productMatchBadge = productMatch === true
    ? <Tag icon={<CheckCircleOutlined />} color="success">匹配</Tag>
    : productMatch === false
    ? <Tag icon={<CloseCircleOutlined />} color="error">不匹配</Tag>
    : <Tag icon={<MinusCircleOutlined />} color="default">未校验</Tag>

  const refundTimelineItems = []
  if (detail.created_at) refundTimelineItems.push({ color: 'blue', children: `创建案件 ${new Date(detail.created_at).toLocaleString()}` })
  if (detail.status !== 'CREATED') refundTimelineItems.push({ color: 'blue', children: '进入处理流程' })
  if (detail.status === 'SUSPENDED') refundTimelineItems.push({ color: 'orange', children: '挂起等待人工审批' })
  if (detail.decision === 'APPROVE') refundTimelineItems.push({ color: 'green', children: '审批通过，执行退款' })
  if (detail.decision === 'REJECT') refundTimelineItems.push({ color: 'red', children: '已驳回' })
  if (detail.refund_status === 'EXECUTED') refundTimelineItems.push({ color: 'green', children: `退款完成（${detail.refund_ref || ''}）` })
  if (detail.status === 'COMPLETED') refundTimelineItems.push({ color: 'green', children: '案件完结' })
  if (detail.status === 'REJECTED' || detail.status === 'FAILED') refundTimelineItems.push({ color: 'red', children: '案件结束' })

  return (
    <AppLayout>
      <Space direction="vertical" size="middle" style={{ width: '100%' }}>
        <Card
          title={
            <Space>
              <span>案件详情</span>
              <Tag color={sm.color}>{sm.text}</Tag>
              {detail.risk_level && <Tag color={rm.color}>{rm.text}</Tag>}
            </Space>
          }
          extra={<Button onClick={load}>刷新</Button>}
        >
          <Descriptions column={2} size="small" bordered>
            <Descriptions.Item label="案件号">{detail.case_id}</Descriptions.Item>
            <Descriptions.Item label="订单号">{detail.order_id}</Descriptions.Item>
            <Descriptions.Item label="申请人">
              {detail.applicant ? (
                <Space>
                  <span>{detail.applicant.display_name}</span>
                  <Tag color={detail.applicant.refund_rate >= 0.5 ? 'red' : 'default'}>
                    退款率 {(detail.applicant.refund_rate * 100).toFixed(0)}%
                  </Tag>
                </Space>
              ) : (
                '—'
              )}
            </Descriptions.Item>
            <Descriptions.Item label="历史订单/案件">{detail.applicant?.total_cases ?? '—'}</Descriptions.Item>
            <Descriptions.Item label="退款金额">{detail.amount_yuan} 元</Descriptions.Item>
            <Descriptions.Item label="币种">{detail.currency}</Descriptions.Item>
            <Descriptions.Item label="欺诈分">{detail.fraud_score ?? '—'}</Descriptions.Item>
            <Descriptions.Item label="舆情分">{detail.sentiment_score ?? '—'}</Descriptions.Item>
            <Descriptions.Item label="OCR 置信度">{detail.ocr_confidence ?? '—'}</Descriptions.Item>
            <Descriptions.Item label="退款状态">{detail.refund_status || '—'}</Descriptions.Item>
            <Descriptions.Item label="退款流水号" span={2}>
              {detail.refund_ref || '—'}
            </Descriptions.Item>
            <Descriptions.Item label="决策" span={2}>
              {detail.decision || '—'}
            </Descriptions.Item>
            <Descriptions.Item label="决策依据" span={2}>
              {detail.decision_reason || '—'}
            </Descriptions.Item>
            <Descriptions.Item label="投诉内容" span={2}>
              {detail.complaint_text || '—'}
            </Descriptions.Item>
            <Descriptions.Item label="审批意见" span={2}>
              {detail.review_comment || '—'}
            </Descriptions.Item>
            <Descriptions.Item label="Trace ID" span={2}>
              <Typography.Text copyable style={{ fontSize: 12 }}>{detail.trace_id}</Typography.Text>
            </Descriptions.Item>
          </Descriptions>
        </Card>

        {detail.source === 'customer_portal' && (
          <Card title="赔付合理性与反薅羊毛核验" size="small">
            <Descriptions column={2} size="small" bordered>
              <Descriptions.Item label="问题程度">{refundGuard.issue_severity_label || '—'}</Descriptions.Item>
              <Descriptions.Item label="处理类型">
                <Tag color={refundGuard.partial_refund ? 'blue' : 'gold'}>{refundGuard.partial_refund ? '部分退款' : '全额处理'}</Tag>
              </Descriptions.Item>
              <Descriptions.Item label="申请金额">¥{detail.amount_yuan}</Descriptions.Item>
              <Descriptions.Item label="系统建议">
                {refundGuard.recommended_amount_cent != null ? `¥${(refundGuard.recommended_amount_cent / 100).toFixed(2)}` : '—'}
              </Descriptions.Item>
              <Descriptions.Item label="申请时可退金额">
                {refundGuard.refundable_cent_at_request != null ? `¥${(refundGuard.refundable_cent_at_request / 100).toFixed(2)}` : '—'}
              </Descriptions.Item>
              <Descriptions.Item label="申请占比">
                {refundGuard.requested_ratio != null ? `${(refundGuard.requested_ratio * 100).toFixed(0)}%` : '—'}
              </Descriptions.Item>
              <Descriptions.Item label="OCR 金额核验">
                {refundGuard.ocr_amount_match == null
                  ? <Tag>未识别到金额</Tag>
                  : refundGuard.ocr_amount_match
                  ? <Tag color="success">一致</Tag>
                  : <Tag color="error">不一致，必须人工</Tag>}
              </Descriptions.Item>
              <Descriptions.Item label="OCR 订单号核验">
                {refundGuard.ocr_order_match == null
                  ? <Tag>未识别到订单号</Tag>
                  : refundGuard.ocr_order_match
                  ? <Tag color="success">一致</Tag>
                  : <Tag color="error">不一致，必须人工</Tag>}
              </Descriptions.Item>
              <Descriptions.Item label="近期申请">
                24小时 {refundGuard.recent_refunds_24h ?? 0} 次 · 7天 {refundGuard.recent_refunds_7d ?? 0} 次 · 30天 {refundGuard.recent_refunds_30d ?? 0} 次
              </Descriptions.Item>
              <Descriptions.Item label="异常信号">
                {abuseSignals.length
                  ? <Space wrap>{abuseSignals.map((signal) => <Tag color="red" key={signal}>{signal}</Tag>)}</Space>
                  : <Tag color="success">未发现明显异常</Tag>}
              </Descriptions.Item>
            </Descriptions>
          </Card>
        )}

        <Card title="多 Agent 处理链路">
          <AgentFlow
            runs={detail.agent_runs}
            status={detail.status}
            decision={detail.decision}
            refundStatus={detail.refund_status}
          />
        </Card>

        {/* Langfuse LLM 观测：主管/管理员可见 */}
        {canViewTrace && <TraceCard trace={trace} />}

        {/* 订单真实性校验 */}
        {detail.is_verified_order !== undefined && (
          <Card title="订单真实性校验" size="small">
            <Descriptions column={2} size="small" bordered>
              <Descriptions.Item label="校验结果">{orderVerifyBadge}</Descriptions.Item>
              <Descriptions.Item label="原始订单金额（分）">
                {detail.verified_order_amount ?? '—'}
              </Descriptions.Item>
              <Descriptions.Item label="错误信息" span={2}>
                {detail.order_verify_error || '—'}
              </Descriptions.Item>
            </Descriptions>
          </Card>
        )}

        {/* 商品一致性校验 */}
        {detail.product_match !== undefined && (
          <Card title="商品一致性校验" size="small">
            <Descriptions column={2} size="small" bordered>
              <Descriptions.Item label="比对结果">{productMatchBadge}</Descriptions.Item>
              <Descriptions.Item label="一致性风险">
                {detail.product_consistency_risk ? (
                  <Tag color={detail.product_consistency_risk === 'HIGH' ? 'red' : detail.product_consistency_risk === 'MEDIUM' ? 'orange' : 'green'}>
                    {detail.product_consistency_risk === 'HIGH' ? '高风险' : detail.product_consistency_risk === 'MEDIUM' ? '中风险' : '低风险'}
                  </Tag>
                ) : '—'}
              </Descriptions.Item>
              <Descriptions.Item label="投诉提及商品">{detail.claimed_product || '—'}</Descriptions.Item>
              <Descriptions.Item label="订单实际商品">{detail.purchased_product || '—'}</Descriptions.Item>
            </Descriptions>
          </Card>
        )}

        {/* 退款状态时间线 */}
        {refundTimelineItems.length > 0 && (
          <Card title="退款状态流转" size="small">
            <Timeline items={refundTimelineItems} />
          </Card>
        )}

        {detail.risk && (
          <Card title="风险评估">
            <Space wrap>
              <Tag color={rm.color}>风险等级：{rm.text}</Tag>
              <Typography.Text>欺诈分 {detail.risk.fraud_score} · 舆情分 {detail.risk.sentiment_score}</Typography.Text>
            </Space>
            {detail.risk.risk_factors && (
              <Typography.Paragraph style={{ marginTop: 12, marginBottom: 0 }}>
                <pre style={{ whiteSpace: 'pre-wrap', margin: 0 }}>
                  {JSON.stringify(detail.risk.risk_factors, null, 2)}
                </pre>
              </Typography.Paragraph>
            )}
          </Card>
        )}

        {detail.evidences.length > 0 && (
          <Card title="凭证 / OCR">
            <List
              dataSource={detail.evidences}
              renderItem={(e) => (
                <List.Item
                  actions={
                    canEditOcr
                      ? [
                          <Button
                            key="edit"
                            size="small"
                            icon={<EditOutlined />}
                            onClick={() => openOcrEditor(e)}
                          >
                            修正 OCR
                          </Button>,
                        ]
                      : undefined
                  }
                >
                  <List.Item.Meta
                    title={
                      <Space>
                        {e.file_name}
                        {e.ocr_corrected && <Tag color="green">人工修正</Tag>}
                        <Tag>{e.ocr_confidence != null ? `置信度 ${e.ocr_confidence.toFixed(2)}` : '未识别'}</Tag>
                      </Space>
                    }
                    description={e.ocr_text || '（无 OCR 文本）'}
                  />
                </List.Item>
              )}
            />
          </Card>
        )}

        {canDecide && (
          <Card title="人工审批">
            <Alert
              type="warning"
              showIcon
              style={{ marginBottom: 16 }}
              message="该案件因高风险/低置信度/模型异常转人工，请审慎决策。"
            />
            <Row gutter={12}>
              <Col flex="auto">
                <Input.TextArea
                  rows={2}
                  value={comment}
                  onChange={(e) => setComment(e.target.value)}
                  placeholder="审批意见（可选）"
                />
              </Col>
              <Col>
                <Space direction="vertical">
                  <Button type="primary" loading={acting} onClick={() => decide('APPROVE')}>
                    批准退款
                  </Button>
                  <Button danger loading={acting} onClick={() => decide('REJECT')}>
                    驳回
                  </Button>
                </Space>
              </Col>
            </Row>
          </Card>
        )}

        {/* OCR 修正弹窗 */}
        <Modal
          title={`修正 OCR 结果 — ${ocrEditing?.fileName || ''}`}
          open={ocrModalOpen}
          onCancel={() => setOcrModalOpen(false)}
          onOk={submitOcrCorrection}
          confirmLoading={ocrSubmitting}
          destroyOnClose
        >
          <Form form={ocrForm} layout="vertical">
            <Form.Item label="原始 OCR 文本">
              <Typography.Paragraph
                style={{
                  background: '#f5f5f5',
                  padding: 8,
                  borderRadius: 4,
                  maxHeight: 150,
                  overflow: 'auto',
                  whiteSpace: 'pre-wrap',
                  marginBottom: 0,
                }}
              >
                {ocrEditing?.originalText || '（空）'}
              </Typography.Paragraph>
            </Form.Item>
            <Form.Item
              name="corrected_text"
              label="修正后文本"
              rules={[{ required: true, message: '请输入修正后的 OCR 文本' }]}
            >
              <Input.TextArea rows={6} placeholder="输入修正后的文本内容" />
            </Form.Item>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              修正后置信度将设为 1.0（人工确认），决策时将跳过 OCR 置信度检查。
            </Typography.Text>
          </Form>
        </Modal>
      </Space>
    </AppLayout>
  )
}
