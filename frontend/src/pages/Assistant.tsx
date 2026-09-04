import {
  CloseOutlined,
  CustomerServiceOutlined,
  OrderedListOutlined,
  RedoOutlined,
  RobotOutlined,
  SafetyCertificateOutlined,
  SendOutlined,
  ShoppingOutlined,
  UserOutlined,
} from '@ant-design/icons'
import { Button, Input, Tag, Typography, message } from 'antd'
import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { askAssistant, type AssistantReply, type AssistantResultItem } from '../api'
import VoiceInputButton from '../components/VoiceInputButton'

interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  text: string
  citations?: string[]
  action?: string | null
  source?: 'text' | 'voice'
  results?: AssistantResultItem[]
  generator?: string
  originalQuestion?: string
  handoffUsed?: boolean
}

interface AssistantProps {
  embedded?: boolean
  onClose?: () => void
}

const suggestions = ['找灰色连帽拉链卫衣', '给我看看黑色的裤子', '查询订单 SO2026090100001', '7 天无理由退货有什么要求？']

function ResultLink({ item, onNavigate }: { item: AssistantResultItem; onNavigate?: () => void }) {
  if (item.kind === 'product') {
    return (
      <Link className="assistant-result-card assistant-product-result" to={item.url} onClick={onNavigate}>
        {item.image_url
          ? <img src={item.image_url} alt={item.title} />
          : <span className="assistant-result-icon"><ShoppingOutlined /></span>}
        <span className="assistant-result-copy">
          <strong>{item.title}</strong>
          <small>{item.color} · {item.fabric}</small>
          <span className="assistant-result-price">¥{item.price_yuan}</span>
        </span>
        <span className="assistant-result-action">查看商品</span>
      </Link>
    )
  }
  const isRefund = item.kind === 'refund'
  return (
    <Link className="assistant-result-card assistant-record-result" to={item.url} onClick={onNavigate}>
      <span className={`assistant-result-icon ${isRefund ? 'refund' : 'order'}`}>
        {isRefund ? <RedoOutlined /> : <OrderedListOutlined />}
      </span>
      <span className="assistant-result-copy">
        <strong>{isRefund ? item.product_name || '退款详情' : item.title}</strong>
        <small>{isRefund ? `订单 ${item.order_no}` : item.items?.map((product) => product.name).join('、')}</small>
        <span>{item.status_label} · ¥{isRefund ? item.amount_yuan : item.total_yuan}</span>
      </span>
      <span className="assistant-result-action">查看详情</span>
    </Link>
  )
}

export default function Assistant({ embedded = false, onClose }: AssistantProps) {
  const navigate = useNavigate()
  const sessionId = useRef<string>()
  const messageListRef = useRef<HTMLDivElement>(null)
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [connectingModel, setConnectingModel] = useState(false)
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      id: 'welcome',
      role: 'assistant',
      text: '您好，我可以按颜色、类别、面料和版型帮您找衣服，也能用订单号查询本人订单或退款详情。您可以打字，也可以直接说。',
      generator: 'template',
    },
  ])

  useEffect(() => {
    const list = messageListRef.current
    if (list) list.scrollTop = list.scrollHeight
  }, [messages, sending])

  const closePanel = () => {
    if (onClose) onClose()
    else navigate('/shop')
  }

  const send = async (
    text: string,
    source: 'text' | 'voice' = 'text',
    useModelFallback = false,
  ) => {
    const question = text.trim()
    if (!question || sending) return
    setMessages((current) => [...current, {
      id: `u-${Date.now()}`,
      role: 'user',
      text: useModelFallback ? '请大模型客服继续回答刚才的问题。' : question,
      source,
    }])
    setInput('')
    setSending(true)
    setConnectingModel(useModelFallback)
    try {
      const response: AssistantReply = await askAssistant(question, sessionId.current, source, useModelFallback)
      sessionId.current = response.session_id
      setMessages((current) => [...current, {
        id: `a-${Date.now()}`,
        role: 'assistant',
        text: response.answer,
        citations: response.citations,
        action: response.action,
        results: response.data || undefined,
        generator: response.generator,
        originalQuestion: question,
      }])
    } catch (error: any) {
      message.error(error.message || '客服暂时无法回答')
      setMessages((current) => [...current, {
        id: `e-${Date.now()}`,
        role: 'assistant',
        text: useModelFallback
          ? '大模型客服暂时无法接入，请稍后再试。'
          : '服务暂时不可用，您仍可到“我的订单”手动提交退款。',
        generator: useModelFallback ? 'fallback_unavailable' : 'template',
      }])
    } finally {
      setSending(false)
      setConnectingModel(false)
    }
  }

  const requestModelFallback = (item: ChatMessage) => {
    if (!item.originalQuestion || sending) return
    setMessages((current) => current.map((messageItem) => (
      messageItem.id === item.id ? { ...messageItem, handoffUsed: true } : messageItem
    )))
    void send(item.originalQuestion, 'text', true)
  }

  return (
    <div className={`assistant-shell ${embedded ? 'assistant-overlay-shell' : ''}`}>
      <header className="assistant-panel-header">
        <span className="assistant-header-avatar"><RobotOutlined /></span>
        <span className="assistant-header-copy">
          <strong>MISTER 智能客服</strong>
          <small><i /> 在线为您服务</small>
        </span>
        <Button
          className="assistant-close-button"
          type="text"
          icon={<CloseOutlined />}
          onClick={closePanel}
          aria-label="返回购物页面"
        >
          返回购物
        </Button>
      </header>

      <div className="assistant-workspace">
        <aside className="assistant-side">
          <div className="assistant-side-heading">
            <CustomerServiceOutlined />
            <div>
              <Typography.Title level={4}>有问题，直接问</Typography.Title>
              <Typography.Text>商品、订单、退款都能查</Typography.Text>
            </div>
          </div>
          <Typography.Text strong>大家常问</Typography.Text>
          <div className="assistant-suggestions">
            {suggestions.map((text) => <Button key={text} size="small" onClick={() => send(text)}>{text}</Button>)}
          </div>
          <div className="assistant-trust-note">
            <SafetyCertificateOutlined />
            <span>订单和退款只查询当前账号；回答会说明来自知识库还是大模型。</span>
          </div>
        </aside>

        <section className="assistant-main">
          <div ref={messageListRef} className="message-list" aria-live="polite">
            {messages.map((item) => (
              <div key={item.id} className={`message-row ${item.role}`}>
                <span className="message-avatar">
                  {item.role === 'assistant' ? <RobotOutlined /> : <UserOutlined />}
                </span>
                <div className="message-bubble">
                  <div className="message-meta">
                    {item.role === 'assistant' && item.generator === 'deepseek' && <Tag color="blue">大模型客服 · DeepSeek</Tag>}
                    {item.source === 'voice' && <Tag color="cyan">语音转写</Tag>}
                  </div>
                  <div className="message-text">{item.text}</div>
                  {item.citations?.length ? (
                    <div className="message-citations">
                      {item.citations.map((citation) => <Tag key={citation} color="green">来源 {citation}</Tag>)}
                    </div>
                  ) : null}
                  {item.results?.length ? (
                    <div className="assistant-results">
                      {item.results.map((result) => (
                        <ResultLink key={`${result.kind}-${result.url}`} item={result} onNavigate={embedded ? closePanel : undefined} />
                      ))}
                    </div>
                  ) : null}
                  {item.role === 'assistant' && item.action === 'create_refund' ? (
                    <Button type="link" className="assistant-inline-action" onClick={() => { closePanel(); navigate('/orders') }}>
                      去我的订单申请退款
                    </Button>
                  ) : null}
                  {item.role === 'assistant' && item.action === 'human_handoff' && item.generator === 'template' && !item.handoffUsed ? (
                    <div className="assistant-handoff">
                      <span>本地知识库未覆盖这个问题，可转由 DeepSeek 大模型继续回答。</span>
                      <Button
                        type="primary"
                        icon={<CustomerServiceOutlined />}
                        onClick={() => requestModelFallback(item)}
                        disabled={sending}
                      >
                        转人工客服
                      </Button>
                    </div>
                  ) : null}
                </div>
              </div>
            ))}
            {sending && (
              <div className="message-row assistant">
                <span className="message-avatar"><RobotOutlined /></span>
                <div className="message-bubble assistant-typing">
                  <span /><span /><span />
                  {connectingModel ? '正在连接大模型客服' : '正在查询知识库'}
                </div>
              </div>
            )}
          </div>

          <div className="assistant-input">
            <div className="assistant-input-row">
              <Input.TextArea
                value={input}
                onChange={(event) => setInput(event.target.value)}
                onPressEnter={(event) => {
                  if (!event.shiftKey) {
                    event.preventDefault()
                    void send(input)
                  }
                }}
                autoSize={{ minRows: 1, maxRows: 4 }}
                placeholder="找衣服、输入订单号，或咨询退款和尺码"
                disabled={sending}
              />
              <VoiceInputButton showLabel={false} disabled={sending} onTranscript={(text) => send(text, 'voice')} />
              <Button type="primary" icon={<SendOutlined />} onClick={() => send(input)} loading={sending}>发送</Button>
            </div>
            <Typography.Text type="secondary">知识库优先回答；未命中时由您决定是否切换大模型客服。</Typography.Text>
          </div>
        </section>
      </div>
    </div>
  )
}
