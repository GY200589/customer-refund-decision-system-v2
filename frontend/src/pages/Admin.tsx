import { useCallback, useEffect, useState } from 'react'
import {
  Badge,
  Button,
  Card,
  Descriptions,
  Form,
  Input,
  InputNumber,
  Modal,
  Select,
  Space,
  Switch,
  Table,
  Tabs,
  Tag,
  Typography,
  message,
} from 'antd'
import { ReloadOutlined, PlusOutlined } from '@ant-design/icons'
import AppLayout from '../components/AppLayout'
import {
  createUser,
  getHealth,
  getThresholds,
  listAuditLogs,
  listUsers,
  updateThresholds,
  updateUser,
  type AdminUser,
  type AuditLogItem,
  type HealthStatus,
} from '../api'

const ROLE_OPTIONS = [
  { value: 'agent', label: '客服' },
  { value: 'supervisor', label: '主管' },
  { value: 'admin', label: '管理员' },
]

function ThresholdsTab() {
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [form] = Form.useForm()

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const t = await getThresholds()
      form.setFieldsValue({
        amount_yuan: t.amount_human_review_threshold_cent / 100,
        ocr_confidence_threshold: t.ocr_confidence_threshold,
        fraud_reject_threshold: t.fraud_reject_threshold,
        fraud_review_threshold: t.fraud_review_threshold,
        refund_rate_review_threshold: t.refund_rate_review_threshold,
        refund_rate_reject_threshold: t.refund_rate_reject_threshold,
        tool_filter_amount_yuan: t.tool_filter_amount_max / 100,
        critic_rule_enabled: t.critic_rule_enabled,
        critic_llm_enabled: t.critic_llm_enabled,
        dlp_enabled: t.dlp_enabled,
      })
    } catch (e: any) {
      message.error(e.message)
    } finally {
      setLoading(false)
    }
  }, [form])

  useEffect(() => {
    load()
  }, [load])

  const save = async () => {
    const v = await form.validateFields()
    setSaving(true)
    try {
      await updateThresholds({
        amount_human_review_threshold_cent: Math.round(v.amount_yuan * 100),
        ocr_confidence_threshold: v.ocr_confidence_threshold,
        fraud_reject_threshold: v.fraud_reject_threshold,
        fraud_review_threshold: v.fraud_review_threshold,
        refund_rate_review_threshold: v.refund_rate_review_threshold,
        refund_rate_reject_threshold: v.refund_rate_reject_threshold,
        tool_filter_amount_max: Math.round(v.tool_filter_amount_yuan * 100),
        critic_rule_enabled: v.critic_rule_enabled,
        critic_llm_enabled: v.critic_llm_enabled,
        dlp_enabled: v.dlp_enabled,
        price_deviation_threshold_cent: Math.round(v.price_deviation_threshold_yuan * 100),
      })
      message.success('阈值已保存，对后续案件即时生效')
    } catch (e: any) {
      message.error(e.message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <Card
      title="业务决策阈值"
      extra={
        <Button icon={<ReloadOutlined />} onClick={load}>
          刷新
        </Button>
      }
      style={{ maxWidth: 640 }}
    >
      <Typography.Paragraph type="secondary">
        阈值在决策时实时读取，修改后无需重启即可对新建案件生效；环境变量值为默认值。
      </Typography.Paragraph>
      <Form form={form} layout="vertical" disabled={loading}>
        <Form.Item
          name="amount_yuan"
          label="金额转人工阈值（元）"
          rules={[{ required: true, message: '请输入金额阈值' }]}
          extra="金额 ≥ 该值将转人工审核"
        >
          <InputNumber min={0.01} step={10} precision={2} style={{ width: 240 }} />
        </Form.Item>
        <Form.Item
          name="ocr_confidence_threshold"
          label="OCR 置信度阈值（0~1）"
          rules={[{ required: true, message: '请输入 OCR 置信度阈值' }]}
          extra="置信度 < 该值将转人工复核"
        >
          <InputNumber min={0} max={1} step={0.05} precision={2} style={{ width: 240 }} />
        </Form.Item>
        <Form.Item
          name="fraud_reject_threshold"
          label="欺诈分拒绝阈值（0~100）"
          rules={[{ required: true, message: '请输入拒绝阈值' }]}
          extra="欺诈分 ≥ 该值将直接拒绝"
        >
          <InputNumber min={0} max={100} step={1} precision={0} style={{ width: 240 }} />
        </Form.Item>
        <Form.Item
          name="fraud_review_threshold"
          label="欺诈分复核阈值（0~100）"
          rules={[{ required: true, message: '请输入复核阈值' }]}
          extra="欺诈分 ≥ 该值（且未达拒绝阈值）将转人工"
        >
          <InputNumber min={0} max={100} step={1} precision={0} style={{ width: 240 }} />
        </Form.Item>
        <Form.Item
          name="refund_rate_review_threshold"
          label="用户退款率复核阈值（0~1）"
          rules={[{ required: true, message: '请输入退款率复核阈值' }]}
          extra="历史退款率达到该值，且本次申请 80% 以上时转人工复核"
        >
          <InputNumber min={0} max={1} step={0.05} precision={2} style={{ width: 240 }} />
        </Form.Item>
        <Form.Item
          name="refund_rate_reject_threshold"
          label="用户退款率拒绝阈值（0~1）"
          rules={[{ required: true, message: '请输入退款率拒绝阈值' }]}
          extra="历史退款率达到该值，且本次申请 80% 以上时拒绝"
        >
          <InputNumber min={0} max={1} step={0.05} precision={2} style={{ width: 240 }} />
        </Form.Item>

        <Typography.Title level={5} style={{ marginTop: 24 }}>安全配置（工单6）</Typography.Title>
        <Form.Item
          name="critic_rule_enabled"
          label="Critic 规则快速路"
          valuePropName="checked"
          extra="25 条预编译正则注入拦截开关"
        >
          <Switch />
        </Form.Item>
        <Form.Item
          name="critic_llm_enabled"
          label="Critic LLM 深度检测"
          valuePropName="checked"
          extra="LLM 检测未知攻击模式（默认关闭）"
        >
          <Switch />
        </Form.Item>
        <Form.Item
          name="dlp_enabled"
          label="DLP 数据脱敏"
          valuePropName="checked"
          extra="入站/出站双通道脱敏开关"
        >
          <Switch />
        </Form.Item>
        <Form.Item
          name="tool_filter_amount_yuan"
          label="ToolFilter 金额上限（元）"
          extra="单笔退款金额上限，超限直接拦截"
        >
          <InputNumber min={0.01} step={100} precision={2} style={{ width: 240 }} />
        </Form.Item>

        <Typography.Title level={5} style={{ marginTop: 24 }}>订单校验配置</Typography.Title>
        <Form.Item
          name="price_deviation_threshold_yuan"
          label="价格偏差阈值（元）"
          extra="退款金额超出订单金额 + 该阈值时转人工"
        >
          <InputNumber min={0} step={10} precision={2} style={{ width: 240 }} />
        </Form.Item>

        <Button type="primary" loading={saving} onClick={save}>
          保存阈值
        </Button>
      </Form>
    </Card>
  )
}

function UsersTab() {
  const [users, setUsers] = useState<AdminUser[]>([])
  const [loading, setLoading] = useState(false)
  const [open, setOpen] = useState(false)
  const [editing, setEditing] = useState<AdminUser | null>(null)
  const [saving, setSaving] = useState(false)
  const [form] = Form.useForm()

  const load = useCallback(async () => {
    setLoading(true)
    try {
      setUsers(await listUsers())
    } catch (e: any) {
      message.error(e.message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const openCreate = () => {
    setEditing(null)
    form.resetFields()
    setOpen(true)
  }

  const openEdit = (u: AdminUser) => {
    setEditing(u)
    form.setFieldsValue({ role: u.role, display_name: u.display_name, is_active: u.is_active, password: '' })
    setOpen(true)
  }

  const submit = async () => {
    const v = await form.validateFields()
    setSaving(true)
    try {
      if (editing) {
        await updateUser(editing.id, {
          role: v.role,
          display_name: v.display_name,
          is_active: v.is_active,
          password: v.password || undefined,
        })
        message.success('用户已更新')
      } else {
        await createUser({ username: v.username, password: v.password, role: v.role, display_name: v.display_name })
        message.success('用户已创建')
      }
      setOpen(false)
      load()
    } catch (e: any) {
      message.error(e.message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <Card
      title="用户管理"
      extra={
        <Space>
          <Button icon={<ReloadOutlined />} onClick={load}>
            刷新
          </Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
            新建用户
          </Button>
        </Space>
      }
    >
      <Table
        rowKey="id"
        loading={loading}
        dataSource={users}
        pagination={false}
        columns={[
          { title: 'ID', dataIndex: 'id', width: 60 },
          { title: '用户名', dataIndex: 'username' },
          { title: '姓名', dataIndex: 'display_name' },
          {
            title: '角色',
            dataIndex: 'role',
            render: (v) => {
              const m = ROLE_OPTIONS.find((o) => o.value === v)
              return <Tag color={v === 'admin' ? 'red' : v === 'supervisor' ? 'orange' : 'blue'}>{m?.label || v}</Tag>
            },
          },
          {
            title: '状态',
            dataIndex: 'is_active',
            render: (v) => (v ? <Badge status="success" text="启用" /> : <Badge status="default" text="禁用" />),
          },
          {
            title: '创建时间',
            dataIndex: 'created_at',
            render: (v) => (v ? new Date(v).toLocaleString() : '—'),
          },
          {
            title: '操作',
            render: (_, u) => (
              <Button size="small" type="link" onClick={() => openEdit(u)}>
                编辑
              </Button>
            ),
          },
        ]}
      />

      <Modal
        title={editing ? `编辑用户：${editing.username}` : '新建用户'}
        open={open}
        onCancel={() => setOpen(false)}
        onOk={submit}
        confirmLoading={saving}
        destroyOnClose
      >
        <Form form={form} layout="vertical" initialValues={{ role: 'agent', is_active: true }}>
          {!editing && (
            <Form.Item name="username" label="用户名" rules={[{ required: true, message: '请输入用户名' }]}>
              <Input />
            </Form.Item>
          )}
          <Form.Item
            name="password"
            label={editing ? '重置密码（留空则不修改）' : '密码'}
            rules={editing ? [] : [{ required: true, min: 8, message: '密码至少 8 位' }]}
          >
            <Input.Password />
          </Form.Item>
          <Form.Item name="display_name" label="显示姓名">
            <Input />
          </Form.Item>
          <Form.Item name="role" label="角色" rules={[{ required: true, message: '请选择角色' }]}>
            <Select options={ROLE_OPTIONS} />
          </Form.Item>
          <Form.Item name="is_active" label="启用" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Form>
      </Modal>
    </Card>
  )
}

function AuditTab() {
  const [data, setData] = useState<AuditLogItem[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)
  const [caseId, setCaseId] = useState('')
  const [action, setAction] = useState('')
  const [page, setPage] = useState(1)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const res = await listAuditLogs({ case_id: caseId, action, limit: 20, offset: (page - 1) * 20 })
      setData(res.items)
      setTotal(res.total)
    } catch (e: any) {
      message.error(e.message)
    } finally {
      setLoading(false)
    }
  }, [caseId, action, page])

  useEffect(() => {
    load()
  }, [load])

  return (
    <Card
      title="审计日志"
      extra={
        <Space>
          <Input
            placeholder="按案件号过滤"
            value={caseId}
            onChange={(e) => {
              setCaseId(e.target.value)
              setPage(1)
            }}
            style={{ width: 240 }}
            allowClear
          />
          <Input
            placeholder="按动作过滤"
            value={action}
            onChange={(e) => {
              setAction(e.target.value)
              setPage(1)
            }}
            style={{ width: 180 }}
            allowClear
          />
          <Button icon={<ReloadOutlined />} onClick={load}>
            刷新
          </Button>
        </Space>
      }
    >
      <Table
        rowKey="id"
        loading={loading}
        dataSource={data}
        pagination={{
          total,
          pageSize: 20,
          current: page,
          showTotal: (t) => `共 ${t} 条`,
          onChange: (p) => setPage(p),
        }}
        columns={[
          { title: 'ID', dataIndex: 'id', width: 70 },
          { title: '案件号', dataIndex: 'case_id', ellipsis: true, render: (v) => v || '—' },
          { title: '操作人', dataIndex: 'actor_username', render: (v) => v || '系统' },
          { title: '动作', dataIndex: 'action' },
          {
            title: '变更前',
            dataIndex: 'before_value',
            ellipsis: true,
            render: (v) => (v ? JSON.stringify(v) : '—'),
          },
          {
            title: '变更后',
            dataIndex: 'after_value',
            ellipsis: true,
            render: (v) => (v ? JSON.stringify(v) : '—'),
          },
          {
            title: '时间',
            dataIndex: 'created_at',
            width: 180,
            render: (v) => (v ? new Date(v).toLocaleString() : '—'),
          },
        ]}
      />
    </Card>
  )
}

function HealthTab() {
  const [health, setHealth] = useState<HealthStatus | null>(null)
  const [loading, setLoading] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      setHealth(await getHealth())
    } catch (e: any) {
      message.error(e.message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const statusTag = (s: string) =>
    s === 'ok' ? <Tag color="green">正常</Tag> : <Tag color="red">异常</Tag>

  return (
    <Card
      title="系统健康监控"
      extra={
        <Button icon={<ReloadOutlined />} loading={loading} onClick={load}>
          刷新
        </Button>
      }
      style={{ maxWidth: 640 }}
    >
      {health && (
        <Descriptions column={1} bordered size="small">
          <Descriptions.Item label="整体状态">{statusTag(health.status)}</Descriptions.Item>
          <Descriptions.Item label="版本">{health.version}</Descriptions.Item>
          <Descriptions.Item label="数据库">
            <Space>
              {statusTag(health.checks.database.status)}
              {health.checks.database.latency_ms != null && (
                <Typography.Text type="secondary">{health.checks.database.latency_ms}ms</Typography.Text>
              )}
              {health.checks.database.error && <Tag color="red">{health.checks.database.error}</Tag>}
            </Space>
          </Descriptions.Item>
          <Descriptions.Item label="Redis">
            <Space>
              {statusTag(health.checks.redis.status)}
              {health.checks.redis.latency_ms != null && (
                <Typography.Text type="secondary">{health.checks.redis.latency_ms}ms</Typography.Text>
              )}
              {health.checks.redis.error && <Tag color="red">{health.checks.redis.error}</Tag>}
            </Space>
          </Descriptions.Item>
        </Descriptions>
      )}
    </Card>
  )
}

export default function Admin() {
  return (
    <AppLayout>
      <Tabs
        items={[
          { key: 'thresholds', label: '阈值配置', children: <ThresholdsTab /> },
          { key: 'users', label: '用户管理', children: <UsersTab /> },
          { key: 'audit', label: '审计日志', children: <AuditTab /> },
          { key: 'health', label: '健康监控', children: <HealthTab /> },
        ]}
      />
    </AppLayout>
  )
}
