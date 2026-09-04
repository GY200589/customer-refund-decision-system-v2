import {
  ArrowLeftOutlined,
  CheckCircleOutlined,
  ClockCircleOutlined,
  CloseCircleOutlined,
  FileTextOutlined,
  ShoppingOutlined,
} from '@ant-design/icons'
import { Alert, Button, Card, Descriptions, Empty, Space, Spin, Tag, Timeline, Typography, message } from 'antd'
import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { getCustomerRefund, type CustomerRefundDetail as RefundDetailType } from '../api'

const statusColor: Record<string, string> = {
  CREATED: 'processing', RUNNING: 'processing', SUSPENDED: 'warning',
  APPROVED: 'success', COMPLETED: 'success', REJECTED: 'error', FAILED: 'error',
}

const formatTime = (value: string | null) => value
  ? new Date(value).toLocaleString('zh-CN', { hour12: false })
  : '等待更新'

const timelineColor = (state: string) => {
  if (state === 'error') return 'red'
  if (state === 'process') return 'blue'
  if (state === 'wait') return 'gray'
  return 'green'
}

const timelineIcon = (state: string) => {
  if (state === 'error') return <CloseCircleOutlined />
  if (state === 'process') return <ClockCircleOutlined />
  return <CheckCircleOutlined />
}

export default function CustomerRefundDetail() {
  const { caseId = '' } = useParams()
  const navigate = useNavigate()
  const [detail, setDetail] = useState<RefundDetailType | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let active = true
    setLoading(true)
    getCustomerRefund(caseId)
      .then((result) => active && setDetail(result))
      .catch((error) => active && message.error(error.message || '退款详情加载失败'))
      .finally(() => active && setLoading(false))
    return () => { active = false }
  }, [caseId])

  if (loading) return <div className="empty-state"><Spin size="large" /></div>
  if (!detail) return <div className="empty-state"><Empty description="退款记录不存在" /></div>

  return (
    <div className="refund-detail-page">
      <Button type="text" icon={<ArrowLeftOutlined />} onClick={() => navigate('/refunds')}>返回退款进度</Button>

      <section className="refund-detail-hero">
        <div>
          <Typography.Text>退款金额</Typography.Text>
          <div className="refund-detail-amount">¥{detail.amount_yuan}</div>
          <Typography.Text>{detail.product_name || '整单退款'} · {detail.partial_refund ? '部分退款' : '全额处理'}</Typography.Text>
        </div>
        <Tag color={statusColor[detail.status]}>{detail.friendly_status}</Tag>
      </section>

      <Alert
        className="refund-detail-alert"
        type={['REJECTED', 'FAILED'].includes(detail.status) ? 'warning' : 'info'}
        showIcon
        message={detail.friendly_explanation}
      />

      <div className="refund-detail-grid">
        <Card title="退款进度" className="refund-detail-card">
          <Timeline
            items={detail.timeline.map((step) => ({
              color: timelineColor(step.state),
              dot: timelineIcon(step.state),
              children: (
                <div className="refund-timeline-item">
                  <Typography.Text strong>{step.title}</Typography.Text>
                  <Typography.Text type="secondary">{step.description}</Typography.Text>
                  <small>{formatTime(step.at)}</small>
                </div>
              ),
            }))}
          />
        </Card>

        <Card title="申请信息" className="refund-detail-card">
          <Descriptions column={1} size="small" colon={false}>
            <Descriptions.Item label="案件编号">{detail.case_id}</Descriptions.Item>
            <Descriptions.Item label="订单编号">{detail.order_no}</Descriptions.Item>
            <Descriptions.Item label="退款商品"><ShoppingOutlined /> {detail.product_name || '整单退款'}</Descriptions.Item>
            <Descriptions.Item label="退款原因">{detail.reason}</Descriptions.Item>
            <Descriptions.Item label="问题程度">{detail.issue_severity_label || '未填写'}</Descriptions.Item>
            <Descriptions.Item label="系统建议">{detail.recommended_amount_yuan ? `¥${detail.recommended_amount_yuan}` : '—'}</Descriptions.Item>
            <Descriptions.Item label="金额说明">{detail.amount_explanation || '—'}</Descriptions.Item>
            <Descriptions.Item label="问题说明">{detail.description}</Descriptions.Item>
            <Descriptions.Item label="提交时间">{formatTime(detail.created_at)}</Descriptions.Item>
            <Descriptions.Item label="最近更新">{formatTime(detail.updated_at)}</Descriptions.Item>
            {detail.refund_ref && <Descriptions.Item label="退款流水号">{detail.refund_ref}</Descriptions.Item>}
          </Descriptions>
        </Card>
      </div>

      <Card title="凭证信息" className="refund-detail-card refund-evidence-card">
        {detail.evidence.length ? (
          <Space wrap>
            {detail.evidence.map((file) => (
              <Tag key={file.evidence_id} icon={<FileTextOutlined />}>
                {file.file_name} · {formatTime(file.uploaded_at)}
              </Tag>
            ))}
          </Space>
        ) : <Typography.Text type="secondary">本次申请未上传凭证</Typography.Text>}
      </Card>
    </div>
  )
}
