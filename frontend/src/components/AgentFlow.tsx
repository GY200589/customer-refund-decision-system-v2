import { Fragment } from 'react'
import type { AgentRun } from '../api'

type NodeState = 'done' | 'error' | 'running' | 'waiting' | 'pending'

const AGENTS: { key: string; title: string }[] = [
  { key: 'IntakeAgent', title: '受理校验' },
  { key: 'OrderVerifyAgent', title: '订单校验' },
  { key: 'ProductConsistencyAgent', title: '商品一致性' },
  { key: 'CriticAgent', title: '注入拦截 🔒' },
  { key: 'EvidenceAgent', title: '取证(OCR)' },
  { key: 'MergedRiskAgent', title: '风险评分' },
  { key: 'DecisionPolicy', title: '决策' },
]

function runState(run?: AgentRun): NodeState {
  if (!run) return 'pending'
  if (run.status === 'FAILED') return 'error'
  if (run.status === 'SUCCESS') return 'done'
  return 'running'
}

// 状态灯语义：绿=已完成 / 蓝=处理中(呼吸) / 黄=等待人工(闪烁) / 红=失败 / 灰=待执行
const META: Record<NodeState, { color: string; label: string; symbol: string; anim: string }> = {
  done: { color: '#52c41a', label: '已完成', symbol: '✓', anim: '' },
  error: { color: '#ff4d4f', label: '失败', symbol: '✕', anim: '' },
  running: { color: '#1677ff', label: '处理中', symbol: '', anim: 'agent-pulse' },
  waiting: { color: '#faad14', label: '等待人工', symbol: '!', anim: 'agent-blink' },
  pending: { color: '#bfbfbf', label: '待执行', symbol: '', anim: '' },
}

const LEGEND: NodeState[] = ['done', 'running', 'waiting', 'error', 'pending']

const STYLE = `
.agent-flow { display:flex; flex-direction:column; gap:12px; }
.agent-row { display:flex; align-items:flex-start; flex-wrap:wrap; row-gap:16px; }
.agent-node { display:flex; flex-direction:column; align-items:center; gap:6px; min-width:68px; }
.agent-light {
  width:22px; height:22px; border-radius:50%;
  display:flex; align-items:center; justify-content:center;
  color:#fff; font-size:12px; font-weight:700; line-height:1;
}
.agent-light.agent-blink { animation: agent-blink 1s ease-in-out infinite; }
.agent-light.agent-pulse { animation: agent-pulse 1.2s ease-in-out infinite; }
.agent-title { font-size:12px; font-weight:500; color:rgba(0,0,0,0.85); white-space:nowrap; }
.agent-hint { font-size:11px; line-height:1; }
.agent-arrow { color:rgba(0,0,0,0.25); font-size:16px; margin-top:5px; }
.agent-legend { display:flex; flex-wrap:wrap; gap:12px; align-items:center; font-size:11px; color:rgba(0,0,0,0.55); }
.agent-legend .dot { display:inline-block; width:8px; height:8px; border-radius:50%; margin-right:4px; vertical-align:middle; }
@keyframes agent-blink {
  0%, 100% { opacity:1; box-shadow:0 0 0 0 rgba(250,173,20,0.55); }
  50% { opacity:0.45; box-shadow:0 0 12px 4px rgba(250,173,20,0.85); }
}
@keyframes agent-pulse {
  0%, 100% { box-shadow:0 0 0 0 rgba(22,119,255,0.45); }
  50% { box-shadow:0 0 10px 3px rgba(22,119,255,0.75); }
}
`

const LIFECYCLE_STEPS = [
  { key: 'RUNNING', title: '⏳ 运行中' },
  { key: 'SUSPENDED', title: '⏸ 挂起中' },
  { key: 'COMPLETED', title: '✅ 已完成' },
]

function lifecycleStep(status: string): number {
  if (status === 'COMPLETED' || status === 'APPROVED' || status === 'REJECTED' || status === 'FAILED') return 2
  if (status === 'SUSPENDED') return 1
  return 0
}

export default function AgentFlow({
  runs,
  status,
  decision,
  refundStatus,
}: {
  runs: AgentRun[]
  status: string
  decision?: string | null
  refundStatus?: string | null
}) {
  const byName: Record<string, AgentRun> = {}
  runs.forEach((r) => {
    byName[r.agent_name] = r
  })

  // 核心 5 个 Agent：由 agent_runs 落库记录派生
  const nodes: { key: string; title: string; state: NodeState }[] = AGENTS.map((a) => ({
    key: a.key,
    title: a.title,
    state: runState(byName[a.key]),
  }))

  // 人工审批节点：后端不落 AgentRun，仅通过 interrupt() 挂起并改状态/发事件，故由案件状态派生
  let review: NodeState = 'pending'
  if (status === 'SUSPENDED') review = 'waiting'
  else if (decision === 'HUMAN_REVIEW' && ['APPROVED', 'COMPLETED', 'REJECTED'].includes(status)) review = 'done'
  nodes.push({ key: 'HumanReview', title: '人工审批', state: review })

  // 退款执行 / 驳回：互斥终态
  let execute: NodeState = 'pending'
  if (status === 'COMPLETED' || refundStatus === 'EXECUTED') execute = 'done'
  else if (status === 'APPROVED') execute = 'running'
  nodes.push({ key: 'ExecuteRefund', title: '退款执行', state: execute })

  let reject: NodeState = 'pending'
  if (status === 'REJECTED') reject = 'error'
  nodes.push({ key: 'Reject', title: '驳回', state: reject })

  return (
    <div className="agent-flow">
      <style>{STYLE}</style>
      <div className="agent-row">
        {nodes.map((n, i) => {
          const m = META[n.state]
          return (
            <Fragment key={n.key}>
              {i > 0 && <span className="agent-arrow">→</span>}
              <div className="agent-node" title={`${n.title}：${m.label}`}>
                <span className={`agent-light ${m.anim}`} style={{ background: m.color }}>
                  {m.symbol}
                </span>
                <span className="agent-title">{n.title}</span>
                <span className="agent-hint" style={{ color: m.color }}>
                  {m.label}
                </span>
              </div>
            </Fragment>
          )
        })}
      </div>
      <div className="agent-legend">
        {LEGEND.map((s) => {
          const m = META[s]
          return (
            <span key={s}>
              <span className="dot" style={{ background: m.color }} />
              {m.label}
            </span>
          )
        })}
      </div>
      <div className="agent-lifecycle" style={{ marginTop: 16 }}>
        <span style={{ fontSize: 12, fontWeight: 500, color: 'rgba(0,0,0,0.45)', marginRight: 8 }}>三态流转：</span>
        {LIFECYCLE_STEPS.map((s, i) => {
          const current = lifecycleStep(status)
          const done = current > i
          const active = current === i
          const color = done ? '#52c41a' : active ? '#1677ff' : 'rgba(0,0,0,0.15)'
          const bg = done ? 'rgba(82,196,26,0.08)' : active ? 'rgba(22,119,255,0.08)' : 'transparent'
          return (
            <Fragment key={s.key}>
              {i > 0 && <span style={{ margin: '0 6px', color: 'rgba(0,0,0,0.15)' }}>→</span>}
              <span
                style={{
                  display: 'inline-block',
                  padding: '2px 10px',
                  borderRadius: 4,
                  fontSize: 12,
                  fontWeight: active ? 600 : 400,
                  color,
                  background: bg,
                  border: `1px solid ${color}`,
                  transition: 'all 0.3s',
                }}
              >
                {s.title}
              </span>
            </Fragment>
          )
        })}
      </div>
    </div>
  )
}
