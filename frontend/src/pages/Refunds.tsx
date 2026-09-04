import { CheckCircleOutlined, ClockCircleOutlined, CloseCircleOutlined, ReloadOutlined, RightOutlined } from '@ant-design/icons'
import { Button, Card, Empty, Space, Spin, Steps, Tag, Typography, message } from 'antd'
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { listCustomerRefunds, type CustomerRefund } from '../api'

const statusColor: Record<string, string> = {
  CREATED: 'processing', RUNNING: 'processing', SUSPENDED: 'warning',
  APPROVED: 'success', COMPLETED: 'success', REJECTED: 'error', FAILED: 'error',
}

function stepState(status: string): { current: number; status?: 'error' } {
  if (['REJECTED', 'FAILED'].includes(status)) return { current: 1, status: 'error' }
  if (status === 'SUSPENDED') return { current: 1 }
  if (['APPROVED', 'COMPLETED'].includes(status)) return { current: 2 }
  return { current: 1 }
}

export default function Refunds() {
  const navigate = useNavigate()
  const [refunds, setRefunds] = useState<CustomerRefund[]>([])
  const [loading, setLoading] = useState(true)

  const load = async () => {
    setLoading(true)
    try {
      setRefunds(await listCustomerRefunds())
    } catch (error: any) {
      message.error(error.message || '退款进度加载失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { void load() }, [])

  return (
    <div className="refund-timeline">
      <div className="page-heading section-split">
        <div>
          <Typography.Title level={2}>退款进度</Typography.Title>
          <Typography.Text type="secondary">这里只展示用户能理解的状态，风控分和内部阈值仅供客服后台查看</Typography.Text>
        </div>
        <Button icon={<ReloadOutlined />} onClick={load}>刷新</Button>
      </div>

      {loading ? <div className="empty-state"><Spin size="large" /></div> : refunds.length ? refunds.map((refund) => {
        const state = stepState(refund.status)
        return (
          <Card
            key={refund.case_id}
            className="order-card refund-list-card"
            hoverable
            onClick={() => navigate(`/refunds/${refund.case_id}`)}
            role="link"
            tabIndex={0}
            onKeyDown={(event) => { if (event.key === 'Enter') navigate(`/refunds/${refund.case_id}`) }}
          >
            <Space direction="vertical" size="middle" style={{ width: '100%' }}>
              <div className="order-card-header">
                <div>
                  <Typography.Text strong>{refund.product_name || '整单退款'}</Typography.Text><br />
                  <Typography.Text type="secondary">订单 {refund.order_no}</Typography.Text>
                </div>
                <div style={{ textAlign: 'right' }}>
                  <Typography.Text strong style={{ fontSize: 18 }}>¥{refund.amount_yuan}</Typography.Text><br />
                  <Tag color={statusColor[refund.status]}>{refund.friendly_status}</Tag>
                </div>
              </div>
              <Steps
                size="small"
                current={state.current}
                status={state.status}
                items={[
                  { title: '已提交', icon: <CheckCircleOutlined /> },
                  { title: state.status === 'error' ? '未通过' : '资料核对', icon: state.status === 'error' ? <CloseCircleOutlined /> : <ClockCircleOutlined /> },
                  { title: '处理完成', icon: <CheckCircleOutlined /> },
                ]}
              />
              <Typography.Text type="secondary">
                案件号 {refund.case_id} · {refund.created_at ? new Date(refund.created_at).toLocaleString() : '时间未知'}
              </Typography.Text>
              <Button type="link" className="refund-detail-link" onClick={() => navigate(`/refunds/${refund.case_id}`)}>
                查看退款详情 <RightOutlined />
              </Button>
            </Space>
          </Card>
        )
      }) : <div className="empty-state"><Empty description="暂无退款申请" /></div>}
    </div>
  )
}
