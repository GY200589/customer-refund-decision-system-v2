import {
  CopyOutlined,
  EnvironmentOutlined,
  FileImageOutlined,
  PayCircleOutlined,
  RedoOutlined,
  ReloadOutlined,
  ShoppingOutlined,
  TruckOutlined,
} from '@ant-design/icons'
import {
  Alert,
  Button,
  Card,
  Descriptions,
  Divider,
  Empty,
  Form,
  Input,
  InputNumber,
  Modal,
  Segmented,
  Select,
  Space,
  Spin,
  Steps,
  Tag,
  Typography,
  Upload,
  message,
} from 'antd'
import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import {
  createCustomerRefund,
  getCustomerRefundQuote,
  getCustomerOrder,
  listCustomerOrders,
  uploadCustomerEvidence,
  type CustomerOrder,
  type CustomerRefundQuote,
  type CustomerUpload,
} from '../api'
import VoiceInputButton from '../components/VoiceInputButton'

const refundReasons = [
  { value: 'size', label: '尺码不合适' },
  { value: 'quality', label: '商品质量问题' },
  { value: 'wrong_item', label: '发错商品/颜色/尺码' },
  { value: 'logistics', label: '物流问题' },
  { value: 'other', label: '其他原因' },
]

const statusColor: Record<string, string> = {
  SHIPPED: 'processing', COMPLETED: 'success', CANCELLED: 'default',
}

const formatTime = (value: string | null) => value
  ? new Date(value).toLocaleString('zh-CN', { hour12: false })
  : '时间未知'

function ProductThumb({ src, alt, className = '' }: { src?: string | null; alt: string; className?: string }) {
  return src
    ? <img className={className} src={src} alt={alt} />
    : <span className={`${className} product-image-fallback`} role="img" aria-label={`${alt}图片暂缺`}><ShoppingOutlined /></span>
}

export default function Orders() {
  const [searchParams, setSearchParams] = useSearchParams()
  const linkedOrderNo = searchParams.get('order')
  const [orders, setOrders] = useState<CustomerOrder[]>([])
  const [loading, setLoading] = useState(true)
  const [detail, setDetail] = useState<CustomerOrder | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [refundOpen, setRefundOpen] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [evidence, setEvidence] = useState<CustomerUpload[]>([])
  const [refundQuote, setRefundQuote] = useState<CustomerRefundQuote | null>(null)
  const [quoteLoading, setQuoteLoading] = useState(false)
  const [form] = Form.useForm()
  const selectedItemId = Form.useWatch('item_id', form)
  const selectedReason = Form.useWatch('reason_code', form)
  const selectedSeverity = Form.useWatch('issue_severity', form)

  const loadOrders = async () => {
    setLoading(true)
    try {
      setOrders(await listCustomerOrders())
    } catch (error: any) {
      message.error(error.message || '订单加载失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { void loadOrders() }, [])

  const openDetail = async (orderNo: string) => {
    setDetail(null)
    setDetailLoading(true)
    try {
      setDetail(await getCustomerOrder(orderNo))
    } catch (error: any) {
      message.error(error.message || '订单详情加载失败')
    } finally {
      setDetailLoading(false)
    }
  }

  useEffect(() => {
    if (linkedOrderNo) void openDetail(linkedOrderNo)
  }, [linkedOrderNo])

  const closeDetail = () => {
    setDetail(null)
    if (!searchParams.has('order')) return
    const next = new URLSearchParams(searchParams)
    next.delete('order')
    setSearchParams(next, { replace: true })
  }

  const copyText = async (value: string, label: string) => {
    await navigator.clipboard.writeText(value)
    message.success(`${label}已复制`)
  }

  const openRefund = () => {
    if (!detail) return
    const firstAvailable = detail.items.find((item) => (item.refundable_cent || 0) > 0 && !item.has_active_refund)
    form.setFieldsValue({
      item_id: firstAvailable?.id,
      reason_code: 'size',
      issue_severity: 'moderate',
      description: '',
    })
    setEvidence([])
    setRefundQuote(null)
    setRefundOpen(true)
  }

  useEffect(() => {
    if (!refundOpen || !detail || !selectedItemId || !selectedReason || !selectedSeverity) return
    let active = true
    setQuoteLoading(true)
    getCustomerRefundQuote(detail.order_no, selectedItemId, selectedReason, selectedSeverity)
      .then((quote) => {
        if (!active) return
        setRefundQuote(quote)
        form.setFieldValue('amount_yuan', Number(quote.recommended_amount_yuan))
        setEvidence([])
      })
      .catch((error) => active && message.error(error.message || '退款金额建议加载失败'))
      .finally(() => active && setQuoteLoading(false))
    return () => { active = false }
  }, [refundOpen, detail, selectedItemId, selectedReason, selectedSeverity, form])

  const uploadFile = async (file: File) => {
    setUploading(true)
    try {
      const requestedYuan = Number(form.getFieldValue('amount_yuan') || 0)
      const uploaded = await uploadCustomerEvidence(file, Math.round(requestedYuan * 100))
      setEvidence((current) => [...current, uploaded])
      if (uploaded.ocr_amount_match === false) {
        message.warning(`${file.name} 已上传，但 OCR 金额与申请金额不一致，将转人工核对`)
      } else {
        message.success(`${file.name} 已上传并完成 OCR 预检`)
      }
    } catch (error: any) {
      message.error(error.message || '凭证上传失败')
    } finally {
      setUploading(false)
    }
    return false
  }

  const submitRefund = async () => {
    if (!detail) return
    const values = await form.validateFields()
    setSubmitting(true)
    try {
      const result = await createCustomerRefund(detail.order_no, {
        item_id: values.item_id,
        amount_cent: Math.round(Number(values.amount_yuan) * 100),
        reason_code: values.reason_code,
        issue_severity: values.issue_severity,
        description: values.description,
        evidence: evidence.map(({ file_name, file_hash, file_path }) => ({ file_name, file_hash, file_path })),
      })
      message.success(`退款申请已提交：${result.case_id}`)
      setRefundOpen(false)
      setDetail(await getCustomerOrder(detail.order_no))
      await loadOrders()
    } catch (error: any) {
      message.error(error.message || '退款申请提交失败')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div>
      <div className="page-heading section-split">
        <div>
          <Typography.Title level={2}>我的订单</Typography.Title>
          <Typography.Text type="secondary">模拟下单后，可从这里把退款申请送入原有多 Agent 决策链</Typography.Text>
        </div>
        <Button icon={<ReloadOutlined />} onClick={loadOrders}>刷新</Button>
      </div>

      {loading ? <div className="empty-state"><Spin size="large" /></div> : orders.length ? orders.map((order) => (
        <Card key={order.id} className="order-card">
          <div className="order-card-header">
            <Space direction="vertical" size={2}>
              <Space wrap>
                <Typography.Text strong>{order.order_no}</Typography.Text>
                <Tag color={statusColor[order.status]}>{order.status_label}</Tag>
              </Space>
              <Typography.Text type="secondary">
                {formatTime(order.created_at)} · {order.items.length} 种商品
              </Typography.Text>
            </Space>
            <Space>
              <Typography.Text strong style={{ fontSize: 18 }}>¥{order.total_yuan}</Typography.Text>
              <Button onClick={() => openDetail(order.order_no)}>订单详情</Button>
            </Space>
          </div>
          <div className="order-items">
            {order.items.map((item) => (
              <div className="order-item-row" key={item.id}>
                <div className="order-item-product">
                  <ProductThumb src={item.image_url} alt={item.name} />
                  <Typography.Text strong>{item.name}</Typography.Text>
                </div>
                <Typography.Text type="secondary">{item.size} / {item.color}</Typography.Text>
                <Typography.Text>¥{item.unit_price_yuan} × {item.quantity}</Typography.Text>
              </div>
            ))}
          </div>
        </Card>
      )) : <div className="empty-state"><Empty description="还没有订单，先去购物大厅看看吧" /></div>}

      <Modal
        open={Boolean(detail) || detailLoading}
        title={<Space><ShoppingOutlined />订单详情{detail && <Tag color={statusColor[detail.status]}>{detail.status_label}</Tag>}</Space>}
        width={900}
        styles={{ body: { maxHeight: 'calc(100vh - 210px)', overflowY: 'auto', paddingRight: 8 } }}
        onCancel={closeDetail}
        footer={detail ? [
          <Button key="close" onClick={closeDetail}>关闭</Button>,
          <Button
            key="refund"
            type="primary"
            icon={<RedoOutlined />}
            disabled={!detail.items.some((item) => (item.refundable_cent || 0) > 0 && !item.has_active_refund)}
            onClick={openRefund}
          >
            申请退款
          </Button>,
        ] : null}
      >
        {detailLoading && !detail ? <Spin /> : detail && (
          <div className="order-detail">
            <div className="order-detail-hero">
              <div>
                <Typography.Text type="secondary">实付金额</Typography.Text>
                <div className="order-detail-paid">¥{detail.pricing?.paid_yuan || detail.total_yuan}</div>
                <Typography.Text type="secondary">{detail.payment?.status_label || '支付成功'} · {formatTime(detail.created_at)}</Typography.Text>
              </div>
              <Tag color="orange">{detail.logistics?.status_label || detail.status_label}</Tag>
            </div>

            <Descriptions className="order-detail-meta" size="small" column={{ xs: 1, sm: 2 }} colon={false}>
              <Descriptions.Item label="订单编号">
                <Space size={4}>{detail.order_no}<Button type="text" size="small" icon={<CopyOutlined />} aria-label="复制订单编号" onClick={() => copyText(detail.order_no, '订单编号')} /></Space>
              </Descriptions.Item>
              <Descriptions.Item label="支付方式"><PayCircleOutlined /> {detail.payment?.method || '在线支付（模拟）'}</Descriptions.Item>
              <Descriptions.Item label="支付单号">{detail.payment?.payment_no || '-'}</Descriptions.Item>
              <Descriptions.Item label="下单时间">{formatTime(detail.created_at)}</Descriptions.Item>
              <Descriptions.Item label="收货人"><EnvironmentOutlined /> {detail.recipient?.name || '顾客'} · {detail.recipient?.phone || '手机号已保护'}</Descriptions.Item>
              <Descriptions.Item label="收货地址" span={2}>{detail.recipient?.address || '演示地址'}</Descriptions.Item>
            </Descriptions>

            <Divider />
            <section className="order-detail-section">
              <div className="order-detail-section-title">
                <Typography.Title level={5}><TruckOutlined /> 物流进度</Typography.Title>
                <Typography.Text type="secondary">{detail.logistics?.carrier} · {detail.logistics?.tracking_no}</Typography.Text>
              </div>
              <Steps
                className="order-logistics"
                size="small"
                current={detail.logistics?.current ?? 0}
                items={(detail.logistics?.steps || []).map((step) => ({
                  title: step.title,
                  description: step.description,
                  status: step.state,
                }))}
              />
            </section>

            <Divider />
            <section className="order-detail-section">
              <Typography.Title level={5}>商品清单</Typography.Title>
              <div className="order-detail-products">
                {detail.items.map((item) => (
                  <div className="order-detail-product" key={item.id}>
                    <ProductThumb src={item.image_url} alt={item.name} />
                    <div>
                      <Typography.Text strong>{item.name}</Typography.Text>
                      <Typography.Text type="secondary">{item.sub_category_label} · {item.size} · {item.color}</Typography.Text>
                      {item.has_active_refund && <Tag color="processing">退款处理中</Tag>}
                    </div>
                    <div className="order-detail-line-price">
                      <span>¥{item.unit_price_yuan} × {item.quantity}</span>
                      <small>可退 ¥{item.refundable_yuan ?? item.line_total_yuan ?? item.unit_price_yuan}</small>
                    </div>
                  </div>
                ))}
              </div>
            </section>

            <div className="order-pricing">
              <span>商品小计<strong>¥{detail.pricing?.subtotal_yuan || detail.total_yuan}</strong></span>
              <span>优惠<strong>-¥{detail.pricing?.discount_yuan || '0.00'}</strong></span>
              <span>运费<strong>¥{detail.pricing?.freight_yuan || '0.00'}</strong></span>
              <span className="order-pricing-total">实付款<strong>¥{detail.pricing?.paid_yuan || detail.total_yuan}</strong></span>
            </div>

            <Alert
              className="order-after-sales"
              type={detail.has_active_refund ? 'warning' : 'info'}
              showIcon
              message={detail.has_active_refund ? '售后申请处理中' : '当前订单支持申请售后'}
              description={`已退 ¥${detail.refunded_yuan || '0.00'}，当前可退 ¥${detail.refundable_yuan || detail.total_yuan}。地址、支付和物流信息均为演示数据。`}
            />
          </div>
        )}
      </Modal>

      <Modal
        open={refundOpen}
        title="提交退款申请"
        okText="确认提交"
        cancelText="取消"
        confirmLoading={submitting}
        onOk={submitRefund}
        onCancel={() => setRefundOpen(false)}
        destroyOnClose
      >
        <Form form={form} layout="vertical" requiredMark={false}>
          <Form.Item name="item_id" label="退款商品" rules={[{ required: true, message: '请选择退款商品' }]}>
            <Select
              options={detail?.items.map((item) => ({
                value: item.id,
                label: `${item.name}（可退 ¥${item.refundable_yuan ?? item.unit_price_yuan}）`,
                disabled: item.has_active_refund || (item.refundable_cent ?? item.unit_price_cent) <= 0,
              }))}
            />
          </Form.Item>
          <Form.Item name="reason_code" label="退款原因" rules={[{ required: true, message: '请选择退款原因' }]}>
            <Select options={refundReasons} />
          </Form.Item>
          <Form.Item name="issue_severity" label="问题程度" rules={[{ required: true }]}>
            <Segmented
              block
              options={[
                { value: 'minor', label: '轻微' },
                { value: 'moderate', label: '中度' },
                { value: 'severe', label: '严重' },
              ]}
            />
          </Form.Item>
          <div className="refund-amount-panel">
            <div>
              <Typography.Text type="secondary">系统建议</Typography.Text>
              <strong>{quoteLoading ? '计算中…' : `¥${refundQuote?.recommended_amount_yuan || '0.00'}`}</strong>
              <small>{refundQuote?.explanation || '选择商品、原因和程度后自动计算'}</small>
            </div>
            <Form.Item
              name="amount_yuan"
              label="申请退款金额"
              rules={[
                { required: true, message: '请输入退款金额' },
                {
                  validator: (_, value) => {
                    const amount = Number(value)
                    if (amount <= 0) return Promise.reject(new Error('退款金额必须大于 0'))
                    if (refundQuote && amount * 100 > refundQuote.refundable_cent) {
                      return Promise.reject(new Error(`不能超过可退金额 ¥${refundQuote.refundable_yuan}`))
                    }
                    return Promise.resolve()
                  },
                },
              ]}
            >
              <InputNumber min={0.01} precision={2} prefix="¥" style={{ width: '100%' }} />
            </Form.Item>
          </div>
          {refundQuote && (
            <Alert
              className="refund-policy-alert"
              type={refundQuote.is_partial ? 'info' : 'warning'}
              showIcon
              message={refundQuote.is_partial ? '轻微或中度问题优先部分补偿' : '当前情况可能按全额处理'}
              description="您可以调整金额；明显超过系统建议、凭证金额不一致或存在高频退款行为时，会进入人工核对。"
            />
          )}
          <Form.Item label="问题说明" required>
            <Space.Compact style={{ width: '100%' }}>
              <Form.Item name="description" noStyle rules={[{ required: true, message: '请填写或语音说明退款原因' }]}>
                <Input.TextArea
                  rows={3}
                  aria-label="问题说明"
                  placeholder="可以打字，也可以点右侧麦克风说出原因"
                />
              </Form.Item>
              <VoiceInputButton
                showLabel={false}
                onTranscript={(text) => form.setFieldValue('description', text)}
              />
            </Space.Compact>
          </Form.Item>
          <Form.Item label="凭证照片（质量问题、发错货建议上传）">
            <Upload
              accept="image/*,.pdf"
              showUploadList={false}
              beforeUpload={uploadFile}
              disabled={uploading}
            >
              <Button icon={<FileImageOutlined />} loading={uploading}>上传凭证</Button>
            </Upload>
            <div className="refund-evidence-list">
              {evidence.map((file) => (
                <Tag
                  key={file.file_path}
                  color={file.ocr_amount_match === false ? 'orange' : 'green'}
                  closable
                  onClose={() => setEvidence((current) => current.filter((x) => x.file_path !== file.file_path))}
                >
                  {file.file_name} · {file.ocr_amount_match === false ? '金额待人工核对' : 'OCR 已预检'}
                </Tag>
              ))}
            </div>
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
