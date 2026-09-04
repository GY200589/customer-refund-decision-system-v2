import { useCallback, useEffect, useRef, useState } from 'react'
import { Alert, Button, Card, Descriptions, Empty, Modal, Space, Table, Tag, message } from 'antd'
import { DownloadOutlined, ReloadOutlined, UploadOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import AppLayout from '../components/AppLayout'
import {
  downloadBatchApprovals,
  listReviewTasks,
  uploadBatchApprovals,
  type BatchApprovalResult,
  type ReviewTaskItem,
} from '../api'

export default function ReviewCenter() {
  const navigate = useNavigate()
  const [tasks, setTasks] = useState<ReviewTaskItem[]>([])
  const [loading, setLoading] = useState(false)
  const [downloading, setDownloading] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [result, setResult] = useState<BatchApprovalResult | null>(null)
  const fileInput = useRef<HTMLInputElement>(null)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      setTasks(await listReviewTasks())
    } catch (e: any) {
      message.error(e.message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
    const t = setInterval(load, 5000)
    return () => clearInterval(t)
  }, [load])

  const download = async () => {
    setDownloading(true)
    try {
      const count = await downloadBatchApprovals()
      message.success(`已导出 ${count} 条待审批案件`)
    } catch (e: any) {
      message.error(e.message)
    } finally {
      setDownloading(false)
    }
  }

  const upload = async (file?: File) => {
    if (!file) return
    setUploading(true)
    try {
      const summary = await uploadBatchApprovals(file)
      setResult(summary)
      await load()
    } catch (e: any) {
      message.error(e.message)
    } finally {
      setUploading(false)
      if (fileInput.current) fileInput.current.value = ''
    }
  }

  return (
    <AppLayout>
      <Card
        title="审批中心（待人工审批案件）"
        extra={
          <Button icon={<ReloadOutlined />} onClick={load}>
            刷新
          </Button>
        }
      >
        <Space style={{ marginBottom: 16 }}>
          <Button icon={<DownloadOutlined />} loading={downloading} onClick={download}>
            导出挂起订单
          </Button>
          <Button type="primary" icon={<UploadOutlined />} loading={uploading} onClick={() => fileInput.current?.click()}>
            上传审批结果
          </Button>
          <input
            ref={fileInput}
            type="file"
            accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            hidden
            onChange={(event) => upload(event.target.files?.[0])}
          />
        </Space>
        {tasks.length === 0 && !loading ? (
          <Empty description="当前无待审批案件" />
        ) : (
          <Table
            rowKey={(r) => String(r.task.id)}
            loading={loading}
            dataSource={tasks}
            pagination={false}
            onRow={(r) => ({
              onClick: () => navigate(`/cases/${r.task.case_id}`),
              style: { cursor: 'pointer' },
            })}
            columns={[
              { title: '任务ID', dataIndex: ['task', 'id'] },
              { title: '案件号', dataIndex: ['task', 'case_id'] },
              {
                title: '申请人画像',
                render: (_, r) => {
                  const a = r.task.applicant
                  if (!a) return '—'
                  const high = a.refund_rate >= 0.5
                  return (
                    <Space>
                      <span>{a.display_name}</span>
                      <Tag color={high ? 'red' : 'default'}>
                        退款率 {(a.refund_rate * 100).toFixed(0)}%
                      </Tag>
                      {high && <Tag color="red">疑似薅羊毛</Tag>}
                    </Space>
                  )
                },
              },
              {
                title: '状态',
                dataIndex: ['task', 'status'],
                render: (v) => <Tag color="warning">{v}</Tag>,
              },
              {
                title: '金额核验',
                render: (_, r) => {
                  const guard = r.task.refund_guard
                  const mismatch = guard.ocr_amount_mismatch || guard.ocr_order_mismatch
                  return (
                    <Space direction="vertical" size={2}>
                      <span>申请 ¥{guard.amount_yuan || '—'} / 建议 ¥{guard.recommended_amount_yuan || '—'}</span>
                      <Space wrap size={4}>
                        <Tag color={guard.partial_refund ? 'blue' : 'gold'}>{guard.partial_refund ? '部分退款' : '全额处理'}</Tag>
                        {mismatch && <Tag color="red">OCR 不一致</Tag>}
                        {guard.abuse_signal_count > 0 && <Tag color="red">风控信号 {guard.abuse_signal_count}</Tag>}
                      </Space>
                    </Space>
                  )
                },
              },
              { title: '指派人', dataIndex: ['task', 'assigned_to'], render: (v) => v || '（最小活跃分配）' },
              {
                title: '创建时间 / 等待时长',
                dataIndex: ['task', 'created_at'],
                render: (v, r) => {
                  if (!v) return '—';
                  const hours = (Date.now() - new Date(v).getTime()) / 3600000;
                  const wait = hours < 1 ? `${Math.max(1, Math.floor(hours * 60))} 分钟` : `${hours.toFixed(1)} 小时`;
                  return (
                    <Space>
                      <span>{new Date(v).toLocaleString()}</span>
                      <span style={{ color: '#999' }}>（已等待 {wait}）</span>
                      {r?.task?.escalated && <Tag color="red">已升级</Tag>}
                    </Space>
                  );
                },
              },
              {
                title: '操作',
                render: () => (
                  <Space>
                    <Button size="small" type="link">
                      前往审批
                    </Button>
                  </Space>
                ),
              },
            ]}
          />
        )}
      </Card>

      <Modal title="批量审批结果" open={!!result} footer={null} onCancel={() => setResult(null)}>
        {result && (
          <Space direction="vertical" size="middle" style={{ width: '100%' }}>
            <Descriptions bordered size="small" column={2}>
              <Descriptions.Item label="总数">{result.total}</Descriptions.Item>
              <Descriptions.Item label="批准">{result.approved}</Descriptions.Item>
              <Descriptions.Item label="拒绝">{result.rejected}</Descriptions.Item>
              <Descriptions.Item label="失败">{result.failed}</Descriptions.Item>
            </Descriptions>
            {result.failures.length > 0 && (
              <Alert
                type="warning"
                showIcon
                message="部分案件未处理"
                description={result.failures.map((item) => `${item.case_id}：${item.error}`).join('\n')}
              />
            )}
          </Space>
        )}
      </Modal>
    </AppLayout>
  )
}
