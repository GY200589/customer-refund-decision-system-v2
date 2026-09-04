import { useCallback, useEffect, useState } from 'react'
import {
  Button,
  Card,
  Col,
  Form,
  Input,
  InputNumber,
  Modal,
  Row,
  Select,
  Space,
  Statistic,
  Table,
  Tag,
  Typography,
  Upload,
  message,
} from 'antd'
import {
  CheckCircleOutlined,
  ClockCircleOutlined,
  FileTextOutlined,
  PlusOutlined,
  ReloadOutlined,
  SyncOutlined,
  UploadOutlined,
} from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import {
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import AppLayout from '../components/AppLayout'
import {
  createCase,
  getStatsOverview,
  listCases,
  uploadEvidence,
  type CaseListItem,
  type StatsOverview,
  type UploadEvidenceResult,
} from '../api'
import { riskMeta, statusMeta } from '../labels'

const STATUS_FILTER = [
  { value: '', label: '全部状态' },
  { value: 'CREATED', label: '已创建' },
  { value: 'RUNNING', label: '处理中' },
  { value: 'SUSPENDED', label: '待人工审批' },
  { value: 'COMPLETED', label: '已完成' },
  { value: 'REJECTED', label: '已驳回' },
  { value: 'FAILED', label: '失败' },
]

const PIE_COLORS = ['#52c41a', '#ff4d4f', '#faad14', '#1890ff', '#722ed1', '#8c8c8c']

export default function Dashboard() {
  const navigate = useNavigate()
  const [data, setData] = useState<CaseListItem[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)
  const [stats, setStats] = useState<StatsOverview | null>(null)
  const [statsLoading, setStatsLoading] = useState(false)
  const [status, setStatus] = useState('')
  const [open, setOpen] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [fileList, setFileList] = useState<any[]>([])
  const [uploadedFiles, setUploadedFiles] = useState<{ file_name: string; file_path: string }[]>([])
  const [ocrPreviews, setOcrPreviews] = useState<UploadEvidenceResult[]>([])
  const [form] = Form.useForm()

  // 记录上一次的原始数据，避免后台轮询时无意义重渲染
  const [lastCasesJson, setLastCasesJson] = useState('')
  const [lastStatsJson, setLastStatsJson] = useState('')

  const loadCases = useCallback(
    async (showLoading = true) => {
      if (showLoading) setLoading(true)
      try {
        const res = await listCases(status || undefined)
        const json = JSON.stringify(res)
        if (json !== lastCasesJson) {
          setData(res.items)
          setTotal(res.total)
          setLastCasesJson(json)
        }
      } catch (e: any) {
        if (showLoading) message.error(e.message)
      } finally {
        if (showLoading) setLoading(false)
      }
    },
    [status, lastCasesJson],
  )

  const loadStats = useCallback(
    async (showLoading = true) => {
      if (showLoading) setStatsLoading(true)
      try {
        const res = await getStatsOverview()
        const json = JSON.stringify(res)
        if (json !== lastStatsJson) {
          setStats(res)
          setLastStatsJson(json)
        }
      } catch (e: any) {
        // 统计接口失败不阻塞主流程，静默失败
        console.warn('stats load failed', e)
      } finally {
        if (showLoading) setStatsLoading(false)
      }
    },
    [lastStatsJson],
  )

  const loadAll = useCallback(
    (showLoading = true) => {
      loadCases(showLoading)
      loadStats(showLoading)
    },
    [loadCases, loadStats],
  )

  useEffect(() => {
    // 首次加载显示 loading，之后轮询静默刷新，避免闪烁
    loadAll(true)
    const t = setInterval(() => loadAll(false), 15000)
    return () => clearInterval(t)
  }, [loadAll])

  const submitCreate = async () => {
    const values = await form.validateFields()
    setSubmitting(true)
    try {
      const evidence = uploadedFiles.map((f) => ({ file_name: f.file_name, file_path: f.file_path }))
      let risk_flags: Record<string, any> = {}
      if (values.risk_flags) {
        try {
          risk_flags = JSON.parse(values.risk_flags)
        } catch {
          message.error('风险标记需为合法 JSON 对象')
          setSubmitting(false)
          return
        }
      }
      const res = await createCase({
        order_id: values.order_id,
        amount_cent: Math.round(values.amount_yuan * 100),
        currency: values.currency || 'CNY',
        complaint_text: values.complaint_text || '',
        risk_flags,
        evidence,
      })
      message.success(`案件已创建：${res.case_id}`)
      setOpen(false)
      setFileList([])
      setUploadedFiles([])
      setOcrPreviews([])
      form.resetFields()
      loadAll()
    } catch (e: any) {
      message.error(e.message)
    } finally {
      setSubmitting(false)
    }
  }

  const handleUpload = async (file: File) => {
    setUploading(true)
    try {
      const result = await uploadEvidence(file)
      setUploadedFiles((prev) => [...prev, { file_name: result.file_name, file_path: result.file_path }])

      if (result.ocr_text || result.ocr_fields) {
        setOcrPreviews((prev) => [...prev, result])

        const filled: string[] = []
        const values = form.getFieldsValue()
        if (!values.order_id && result.ocr_fields?.order_id) {
          form.setFieldValue('order_id', result.ocr_fields.order_id)
          filled.push('订单号')
        }
        if (
          !form.isFieldTouched('amount_yuan') &&
          typeof result.ocr_fields?.amount === 'number' &&
          result.ocr_fields.amount > 0
        ) {
          form.setFieldValue('amount_yuan', result.ocr_fields.amount)
          filled.push('金额')
        }
        message.success(
          `${result.file_name} 识别完成${filled.length ? `，已自动填入${filled.join('/')}` : ''}`,
        )
      } else {
        message.success(`${result.file_name} 上传成功`)
      }
    } catch (e: any) {
      message.error(e.message)
    } finally {
      setUploading(false)
    }
    return false
  }

  const pieData = stats
    ? Object.entries(stats.status_distribution).map(([name, value]) => ({
        name: statusMeta(name).text,
        value,
      }))
    : []

  const formatDuration = (seconds: number) => {
    if (seconds < 60) return `${Math.round(seconds)}秒`
    if (seconds < 3600) return `${Math.round(seconds / 60)}分钟`
    return `${(seconds / 3600).toFixed(1)}小时`
  }

  return (
    <AppLayout>
      <Space direction="vertical" size="middle" style={{ width: '100%' }}>
        {/* KPI 概览卡片 */}
        <Row gutter={16}>
          <Col span={6}>
            <Card loading={statsLoading} bordered={false}>
              <Statistic
                title="今日案件"
                value={stats?.today.total ?? 0}
                prefix={<FileTextOutlined />}
                suffix={`/ ${stats?.overall.total ?? 0}`}
              />
            </Card>
          </Col>
          <Col span={6}>
            <Card loading={statsLoading} bordered={false}>
              <Statistic
                title="待人工审批"
                value={stats?.overall.suspended ?? 0}
                prefix={<ClockCircleOutlined />}
                valueStyle={{ color: '#faad14' }}
              />
            </Card>
          </Col>
          <Col span={6}>
            <Card loading={statsLoading} bordered={false}>
              <Statistic
                title="自动审批率"
                value={(stats?.overall.auto_rate ?? 0) * 100}
                precision={1}
                suffix="%"
                prefix={<CheckCircleOutlined />}
                valueStyle={{ color: '#52c41a' }}
              />
            </Card>
          </Col>
          <Col span={6}>
            <Card loading={statsLoading} bordered={false}>
              <Statistic
                title="平均处理时长"
                value={formatDuration(stats?.overall.avg_duration_seconds ?? 0)}
                prefix={<SyncOutlined />}
              />
            </Card>
          </Col>
        </Row>

        {/* 图表区 */}
        <Row gutter={16}>
          <Col span={14}>
            <Card title="近 7 日案件趋势" loading={statsLoading} size="small">
              {stats && (
                <ResponsiveContainer width="100%" height={260}>
                  <LineChart data={stats.trend} margin={{ top: 5, right: 20, left: 0, bottom: 5 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                    <XAxis dataKey="date" tick={{ fontSize: 12 }} />
                    <YAxis tick={{ fontSize: 12 }} />
                    <Tooltip />
                    <Legend />
                    <Line type="monotone" dataKey="total" name="总数" stroke="#1890ff" strokeWidth={2} />
                    <Line type="monotone" dataKey="completed" name="已完成" stroke="#52c41a" strokeWidth={2} />
                    <Line type="monotone" dataKey="rejected" name="已驳回" stroke="#ff4d4f" strokeWidth={2} />
                    <Line type="monotone" dataKey="suspended" name="待审批" stroke="#faad14" strokeWidth={2} />
                  </LineChart>
                </ResponsiveContainer>
              )}
            </Card>
          </Col>
          <Col span={10}>
            <Card title="状态分布" loading={statsLoading} size="small">
              {stats && (
                <ResponsiveContainer width="100%" height={260}>
                  <PieChart>
                    <Pie
                      data={pieData}
                      cx="50%"
                      cy="50%"
                      innerRadius={50}
                      outerRadius={80}
                      paddingAngle={2}
                      dataKey="value"
                      label={({ name, percent }) => `${name} ${(percent * 100).toFixed(0)}%`}
                    >
                      {pieData.map((_, index) => (
                        <Cell key={`cell-${index}`} fill={PIE_COLORS[index % PIE_COLORS.length]} />
                      ))}
                    </Pie>
                    <Tooltip />
                  </PieChart>
                </ResponsiveContainer>
              )}
            </Card>
          </Col>
        </Row>

        {/* 案件列表 */}
        <Card
          title="最新案件"
          size="small"
          extra={
            <Space>
              <Select style={{ width: 140 }} value={status} onChange={setStatus} options={STATUS_FILTER} />
              <Button icon={<ReloadOutlined />} onClick={() => loadAll()}>
                刷新
              </Button>
              <Button type="primary" icon={<PlusOutlined />} onClick={() => setOpen(true)}>
                新建案件
              </Button>
            </Space>
          }
        >
          <Table
            rowKey="case_id"
            loading={loading}
            dataSource={data}
            pagination={{ total, pageSize: 10, showTotal: (t) => `共 ${t} 条` }}
            onRow={(record) => ({ onClick: () => navigate(`/cases/${record.case_id}`), style: { cursor: 'pointer' } })}
            columns={[
              { title: '案件号', dataIndex: 'case_id', ellipsis: true },
              { title: '订单号', dataIndex: 'order_id' },
              { title: '金额(元)', dataIndex: 'amount_yuan', width: 110 },
              {
                title: '风险',
                dataIndex: 'risk_level',
                width: 100,
                render: (v) => {
                  const m = riskMeta(v)
                  return <Tag color={m.color}>{m.text}</Tag>
                },
              },
              {
                title: '状态',
                dataIndex: 'status',
                width: 130,
                render: (v) => {
                  const m = statusMeta(v)
                  return <Tag color={m.color}>{m.text}</Tag>
                },
              },
              { title: '决策', dataIndex: 'decision', width: 130, render: (v) => v || '—' },
              { title: '退款', dataIndex: 'refund_status', width: 110, render: (v) => v || '—' },
              {
                title: '创建时间',
                dataIndex: 'created_at',
                width: 180,
                render: (v) => (v ? new Date(v).toLocaleString() : '—'),
              },
            ]}
          />
        </Card>
      </Space>

      <Modal
        title="新建退款案件"
        open={open}
        onCancel={() => {
          setOpen(false)
          setFileList([])
          setUploadedFiles([])
          setOcrPreviews([])
        }}
        onOk={submitCreate}
        confirmLoading={submitting}
        destroyOnClose
      >
        <Form form={form} layout="vertical" initialValues={{ currency: 'CNY', amount_yuan: 300 }}>
          <Form.Item name="order_id" label="订单号" rules={[{ required: true, message: '请输入订单号' }]}>
            <Input placeholder="如 ORD-2024-0001" />
          </Form.Item>
          <Form.Item name="amount_yuan" label="退款金额（元）" rules={[{ required: true, message: '请输入金额' }]}>
            <InputNumber min={0.01} step={0.01} precision={2} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="currency" label="币种">
            <Input disabled />
          </Form.Item>
          <Form.Item name="complaint_text" label="投诉内容">
            <Input.TextArea rows={3} placeholder="客户投诉描述" />
          </Form.Item>
          <Form.Item name="evidence" label="退款凭证">
            <Upload
              multiple
              accept="image/*,.pdf"
              fileList={fileList}
              beforeUpload={handleUpload}
              onRemove={(file) => {
                const idx = fileList.indexOf(file)
                const removed = uploadedFiles[idx]
                const newFileList = fileList.filter((_, i) => i !== idx)
                setFileList(newFileList)
                setUploadedFiles((prev) => prev.filter((_, i) => i !== idx))
                if (removed) {
                  setOcrPreviews((prev) => prev.filter((p) => p.file_name !== removed.file_name))
                }
              }}
            >
              <Button icon={<UploadOutlined />} loading={uploading}>
                选择凭证文件
              </Button>
            </Upload>
          </Form.Item>
          {ocrPreviews.length > 0 && (
            <Card size="small" title="OCR 识别结果（实时）" style={{ marginBottom: 16 }}>
              {ocrPreviews.map((p, i) => (
                <div key={`${p.file_name}-${i}`} style={{ marginBottom: i < ocrPreviews.length - 1 ? 12 : 0 }}>
                  <Space wrap size={[8, 4]}>
                    <Typography.Text strong ellipsis style={{ maxWidth: 180 }}>
                      {p.file_name}
                    </Typography.Text>
                    {p.ocr_confidence != null && (
                      <Tag color={p.ocr_confidence >= 0.8 ? 'green' : 'orange'}>
                        置信度 {(p.ocr_confidence * 100).toFixed(1)}%
                      </Tag>
                    )}
                    {p.ocr_fields?.order_id && <Tag color="blue">订单号 {p.ocr_fields.order_id}</Tag>}
                    {typeof p.ocr_fields?.amount === 'number' && (
                      <Tag color="red">金额 ¥{p.ocr_fields.amount.toFixed(2)}</Tag>
                    )}
                    {p.ocr_fields?.date && <Tag>日期 {p.ocr_fields.date}</Tag>}
                  </Space>
                  {p.ocr_text && (
                    <Typography.Paragraph
                      type="secondary"
                      ellipsis={{ rows: 2, expandable: true, symbol: '展开全文' }}
                      style={{ fontSize: 12, marginBottom: 0, marginTop: 4, whiteSpace: 'pre-wrap' }}
                    >
                      {p.ocr_text}
                    </Typography.Paragraph>
                  )}
                </div>
              ))}
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                已识别的订单号/金额会自动填入空缺字段（已有内容不会被覆盖），置信度 &lt; 80% 的凭证建案后将转人工复核。
              </Typography.Text>
            </Card>
          )}
          <Form.Item name="risk_flags" label="风险标记（JSON，可选）">
            <Input.TextArea rows={2} placeholder='{"has_malicious_words": true}' />
          </Form.Item>
        </Form>
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          金额以元输入，后端以「分」存储（整数，避免浮点误差）。
        </Typography.Text>
      </Modal>
    </AppLayout>
  )
}
