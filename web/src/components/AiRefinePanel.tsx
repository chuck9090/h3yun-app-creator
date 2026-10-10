import { forwardRef, useCallback, useEffect, useImperativeHandle, useRef, useState } from 'react'
import {
  Alert,
  App as AntApp,
  Button,
  Empty,
  Input,
  List,
  Modal,
  Space,
  Tag,
  Tooltip,
  Typography,
} from 'antd'
import {
  CheckCircleOutlined,
  CloseCircleOutlined,
  HistoryOutlined,
  LoadingOutlined,
  RobotOutlined,
  SendOutlined,
} from '@ant-design/icons'
import {
  errMsg,
  getStageHistory,
  getStages,
  Job,
  JobProgressItem,
  RefineHistoryItem,
  refineStage,
  restoreStage,
  StageHistoryItem,
  StageName,
} from '../api/client'
import { useJob } from '../hooks/useJob'

const ORIGIN_LABEL: Record<string, string> = {
  generate: '生成',
  refine: 'AI 微调',
  edit: '手动保存',
  restore: '回滚',
}

interface UserRec {
  key: string
  type: 'user'
  text: string
}
interface GenRec {
  key: string
  type: 'generate'
  jobId: number
  title: string
  time: string
  status: string
  steps: JobProgressItem[]
  result?: string
  error?: string
}
interface RefRec {
  key: string
  type: 'refine'
  cid: number
  title: string
  time: string
  instruction: string
  status: 'queued' | 'running' | 'done' | 'failed'
  steps: JobProgressItem[]
  result?: string
  changes?: string[]
  error?: string
}
type Rec = UserRec | GenRec | RefRec

export interface AiAssistHandle {
  /** 打开 AI 对话框(供所在步骤的「生成」按钮在触发后台任务后调用,展示进度)。 */
  open: () => void
}

function fmtTime(s: string): string {
  const t = (s || '').trim()
  const m = t.match(/(\d{2}:\d{2}:\d{2})/)
  if (m) return m[1]
  const d = new Date(t.replace(' ', 'T'))
  if (!Number.isNaN(d.getTime())) {
    return [d.getHours(), d.getMinutes(), d.getSeconds()]
      .map((n) => String(n).padStart(2, '0'))
      .join(':')
  }
  return ''
}

/** 从任务结果里提炼「本轮改了什么」的要点。 */
function summarize(job: Job): string[] {
  const r: any = job.result || {}
  const out: string[] = []
  const cs = r.changeSummary
  if (cs && Array.isArray(cs.addedForms) && cs.addedForms.length) {
    out.push('新增表单:' + cs.addedForms.join('、'))
  }
  if (cs && Array.isArray(cs.removedForms) && cs.removedForms.length) {
    out.push('移除表单:' + cs.removedForms.join('、'))
  }
  if (Array.isArray(r.sheets)) {
    let s = `当前 ${r.sheets.length} 张表`
    if (Array.isArray(r.automations)) s += ` / ${r.automations.length} 条自动化`
    out.push(s)
  } else if (typeof r.nodes === 'number' && typeof r.edges === 'number') {
    out.push(`当前流程图:${r.nodes} 个节点 / ${r.edges} 条连线`)
  }
  return out
}

function patchRefineRunning(recs: Rec[], patch: Partial<RefRec>): Rec[] {
  for (let i = recs.length - 1; i >= 0; i--) {
    const r = recs[i]
    if (r.type === 'refine' && r.status === 'running') {
      const n = [...recs]
      n[i] = { ...r, ...patch }
      return n
    }
  }
  return recs
}

function patchRefineByCid(recs: Rec[], cid: number, patch: Partial<RefRec>): Rec[] {
  return recs.map((r) => (r.type === 'refine' && r.cid === cid ? { ...r, ...patch } : r))
}

/** 「本轮之前」的对话上下文(仅已完成的微调轮)。 */
function buildHistory(recs: Rec[], beforeCid: number): RefineHistoryItem[] {
  const out: RefineHistoryItem[] = []
  for (const r of recs) {
    if (r.type === 'user') {
      out.push({ role: 'user', content: r.text })
    } else if (r.type === 'refine') {
      if (r.cid >= beforeCid) break
      if (r.status === 'done') out.push({ role: 'assistant', content: r.result || '已完成' })
    }
  }
  return out
}

/**
 * AI 助手面板(方案 / 业务流程图 / ER 共用)。
 *
 * - 右下角悬浮图标 → 居中大弹窗(上记录 / 下输入);生成与微调**统一**在对话里展示进度;
 * - **生成**:点所在步骤的「生成」按钮后自动打开本弹窗,进度以 agent 轨迹实时呈现;
 * - **微调**:多轮对话(带上下文)、执行中可继续输入(排队)、实时步骤轨迹;
 * - 每条记录显示**时间**与一句**标题**(微调标题由 AI 总结 AI 改动生成);
 * - 关闭弹窗仅隐藏,任务在后台继续,完成后自动刷新内容。
 */
const AiRefinePanel = forwardRef<AiAssistHandle, {
  projectId: number
  stage: StageName
  canWrite: boolean
  disabled?: boolean
  stageLabel: string
  onApplied: () => void
}>(function AiRefinePanel({ projectId, stage, canWrite, disabled, stageLabel, onApplied }, ref) {
  const { message } = AntApp.useApp()
  const [open, setOpen] = useState(false)
  const [input, setInput] = useState('')
  const [recs, setRecs] = useState<Rec[]>([])
  const [stale, setStale] = useState(false)
  const [histOpen, setHistOpen] = useState(false)
  const [hist, setHist] = useState<StageHistoryItem[]>([])
  const [histLoading, setHistLoading] = useState(false)
  const listRef = useRef<HTMLDivElement | null>(null)
  const seqRef = useRef(0)

  useImperativeHandle(ref, () => ({ open: () => setOpen(true) }), [])

  const refineKind = `${stage}_refine`

  const refreshStages = useCallback(() => {
    getStages(projectId)
      .then((s) => setStale(!!s?.[stage]?.stale))
      .catch(() => {
        /* 忽略 */
      })
  }, [projectId, stage])

  useEffect(() => {
    refreshStages()
  }, [refreshStages])

  /* ---------- 生成任务:订阅本阶段的生成 job,渲染为一条记录 ---------- */
  const { job: gjob } = useJob(projectId, stage)
  useEffect(() => {
    if (!gjob) return
    const t = fmtTime(gjob.createdAt)
    const done = gjob.status === 'done'
    const failed = gjob.status === 'failed'
    const title = done
      ? `生成${stageLabel}`
      : failed
        ? `生成${stageLabel}失败`
        : `正在生成${stageLabel}…`
    setRecs((prev) => {
      const idx = prev.findIndex((r) => r.type === 'generate' && r.jobId === gjob.id)
      const rec: GenRec = {
        key: `g${gjob.id}`,
        type: 'generate',
        jobId: gjob.id,
        title,
        time: t,
        status: gjob.status,
        steps: gjob.progress || [],
        result: done ? gjob.detail : undefined,
        error: failed ? gjob.error : undefined,
      }
      if (idx >= 0) {
        const n = [...prev]
        n[idx] = rec
        return n
      }
      return [...prev, rec]
    })
  }, [gjob, stageLabel])

  /* ---------- 微调任务:多轮对话 ---------- */
  const loadHistory = useCallback(async () => {
    setHistLoading(true)
    try {
      const r = await getStageHistory(projectId, stage)
      setHist(r?.items || [])
    } catch (e) {
      message.error(errMsg(e))
    } finally {
      setHistLoading(false)
    }
  }, [projectId, stage, message])

  const { job: rjob, running: rrunning, start: rstart } = useJob(
    projectId,
    refineKind,
    (j: Job) => {
      const summary = (j.result && (j.result as any).summary) || ''
      setRecs((prev) =>
        patchRefineRunning(prev, {
          status: 'done',
          result: j.detail || '已完成本轮微调',
          changes: summarize(j),
          title: summary || j.detail || '已完成微调',
          time: fmtTime(j.createdAt) || fmtTime(j.updatedAt),
        }),
      )
      onApplied()
      refreshStages()
    },
    (j: Job) => {
      setRecs((prev) =>
        patchRefineRunning(prev, { status: 'failed', error: j.error || '未知错误' }),
      )
    },
  )

  useEffect(() => {
    if (rjob && rjob.status === 'running') {
      setRecs((prev) =>
        patchRefineRunning(prev, { steps: rjob.progress || [], time: fmtTime(rjob.createdAt) }),
      )
    }
  }, [rjob])

  function runRefine(cid: number, text: string, history: RefineHistoryItem[]) {
    rstart(() => refineStage(projectId, stage, text, history)).catch((e) => {
      const msg = errMsg(e)
      message.error(msg)
      setRecs((prev) => patchRefineByCid(prev, cid, { status: 'failed', error: msg }))
    })
  }

  // 排队:无正在执行的一轮且有排队行 → 启动最早一条
  useEffect(() => {
    const busy = recs.some((r) => r.type === 'refine' && r.status === 'running')
    if (busy) return
    const next = recs.find((r) => r.type === 'refine' && r.status === 'queued') as
      | RefRec
      | undefined
    if (!next) return
    const cid = next.cid
    const history = buildHistory(recs, cid)
    setRecs((prev) => patchRefineByCid(prev, cid, { status: 'running' }))
    runRefine(cid, next.instruction, history)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [recs])

  useEffect(() => {
    const el = listRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [recs, open])

  function send() {
    const text = input.trim()
    if (!text || !canWrite || disabled) return
    setInput('')
    const uid = `u${(seqRef.current += 1)}`
    const cid = seqRef.current += 1
    const busy = recs.some(
      (r) => r.type === 'refine' && (r.status === 'running' || r.status === 'queued'),
    )
    const history = buildHistory(recs, cid)
    const now = fmtTime(new Date().toString())
    setRecs((prev) => [
      ...prev,
      { key: uid, type: 'user', text },
      {
        key: `r${cid}`,
        type: 'refine',
        cid,
        title: '正在微调…',
        time: now,
        instruction: text,
        steps: [],
        status: busy ? 'queued' : 'running',
      },
    ])
    if (!busy) runRefine(cid, text, history)
  }

  function openHistory() {
    setHistOpen(true)
    loadHistory()
  }

  async function doRestore(it: StageHistoryItem) {
    try {
      await restoreStage(projectId, stage, it.id)
      message.success('已回滚到所选版本')
      setHistOpen(false)
      onApplied()
      refreshStages()
    } catch (e) {
      message.error(errMsg(e))
    }
  }

  const running = rrunning || (!!gjob && gjob.status === 'running')
  const canReply = canWrite && !disabled

  return (
    <>
      <div className="ai-fab">
        <Tooltip
          title={disabled ? `先生成${stageLabel}后才能微调` : `AI 助手 · ${stageLabel}`}
          placement="left"
        >
          <Button
            shape="circle"
            size="large"
            className={`ai-fab-btn${running ? ' is-thinking' : ''}${stale ? ' is-stale' : ''}`}
            disabled={disabled}
            onClick={() => setOpen(true)}
            icon={<RobotOutlined />}
          />
        </Tooltip>
        {running ? (
          <span className="ai-fab-hint">AI 工作中…</span>
        ) : stale ? (
          <span className="ai-fab-hint">上游已更新</span>
        ) : null}
      </div>

      <Modal
        open={open}
        onCancel={() => setOpen(false)}
        footer={null}
        centered
        width={760}
        title={
          <Space size={6} wrap>
            <RobotOutlined />
            <span>AI 助手 · {stageLabel}</span>
            {running ? <Tag color="processing">执行中</Tag> : null}
            {stale ? <Tag color="orange">上游已更新</Tag> : null}
          </Space>
        }
        styles={{ body: { paddingTop: 12 } }}
      >
        <div className="ai-refine-modal">
          {stale ? (
            <Alert
              type="warning"
              showIcon
              style={{ marginBottom: 10 }}
              message="上游内容已更新,当前内容可能已过期"
              description={`建议先重新生成${stageLabel},再做微调,以免与上游不一致。`}
            />
          ) : null}

          <div className="ai-refine-toolbar">
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              生成与微调都在此展示进度;用一句话描述要改的地方,AI 会做**最小改动**,可连续追问。
            </Typography.Text>
            <Button size="small" icon={<HistoryOutlined />} disabled={disabled} onClick={openHistory}>
              历史版本
            </Button>
          </div>

          <div className="ai-refine-log" ref={listRef}>
            {recs.length ? (
              recs.map((r) =>
                r.type === 'user' ? (
                  <div key={r.key} className="ai-refine-msg is-user">
                    {r.text}
                  </div>
                ) : (
                  <article key={r.key} className="ai-round">
                    <header className="ai-round-head">
                      <span className="ai-round-title">{r.title}</span>
                      {r.time ? <time className="ai-round-time">{r.time}</time> : null}
                    </header>
                    <div className="ai-agent">
                      {r.type === 'refine' && r.status === 'queued' ? (
                        <div className="ai-agent-note">排队中,等待上一轮完成…</div>
                      ) : null}
                      {r.steps.map((s, i) => (
                        <div className="ai-step" key={i}>
                          <span className={`ai-step-dot is-${s.level}`} />
                          <span className="ai-step-text">{s.text}</span>
                          {typeof s.pct === 'number' ? (
                            <span className="ai-step-pct">{s.pct}%</span>
                          ) : null}
                        </div>
                      ))}
                      {r.status === 'running' ? (
                        <div className="ai-agent-note">
                          <LoadingOutlined /> 执行中…
                        </div>
                      ) : null}
                      {r.status === 'done' && r.result ? (
                        <div className="ai-agent-result">
                          <div>
                            <CheckCircleOutlined /> {r.result}
                          </div>
                          {r.type === 'refine' && r.changes && r.changes.length ? (
                            <ul className="ai-agent-changes">
                              {r.changes.map((c, i) => (
                                <li key={i}>{c}</li>
                              ))}
                            </ul>
                          ) : null}
                        </div>
                      ) : null}
                      {r.status === 'failed' ? (
                        <div className="ai-agent-error">
                          <CloseCircleOutlined /> {r.error}
                        </div>
                      ) : null}
                    </div>
                  </article>
                ),
              )
            ) : (
              <Typography.Text type="secondary">
                试试:「给客户表增加一个『客户等级』下拉字段」「把流程图里门店模块的流程顺序改为先审后批」。
              </Typography.Text>
            )}
          </div>

          <div className="ai-refine-input">
            <Input.TextArea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder={`描述对${stageLabel}的修改(回车发送,Shift+回车换行)`}
              autoSize={{ minRows: 2, maxRows: 6 }}
              disabled={!canReply}
              onPressEnter={(e) => {
                if ((e.nativeEvent as any)?.isComposing || (e as any)?.keyCode === 229) return
                if (!e.shiftKey) {
                  e.preventDefault()
                  send()
                }
              }}
            />
            <Button
              type="primary"
              icon={<SendOutlined />}
              disabled={!canReply || !input.trim()}
              onClick={send}
            >
              发送
            </Button>
          </div>
          {!canWrite ? <Typography.Text type="secondary">无写入权限</Typography.Text> : null}
          {disabled && canWrite ? (
            <Typography.Text type="secondary">尚未生成{stageLabel},生成后再来微调。</Typography.Text>
          ) : null}
        </div>
      </Modal>

      <Modal
        open={histOpen}
        onCancel={() => setHistOpen(false)}
        footer={null}
        centered
        title={`${stageLabel} · 历史版本`}
      >
        {histLoading ? (
          <Typography.Text type="secondary">加载中…</Typography.Text>
        ) : hist.length ? (
          <List
            size="small"
            dataSource={hist}
            renderItem={(it) => (
              <List.Item
                actions={[
                  <Button key="r" size="small" disabled={!canWrite} onClick={() => doRestore(it)}>
                    回滚
                  </Button>,
                ]}
              >
                <List.Item.Meta
                  title={
                    <Space>
                      <Tag>{ORIGIN_LABEL[it.origin] || it.origin}</Tag>
                      <span>{it.at}</span>
                    </Space>
                  }
                  description={
                    it.instruction
                      ? `指令:${it.instruction}`
                      : it.provider
                        ? `provider=${it.provider}`
                        : ''
                  }
                />
              </List.Item>
            )}
          />
        ) : (
          <Empty description="暂无历史版本" />
        )}
      </Modal>
    </>
  )
})

export default AiRefinePanel
