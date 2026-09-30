import { useCallback, useEffect, useRef, useState } from 'react'
import {
  Alert,
  App as AntApp,
  Button,
  Card,
  Empty,
  Input,
  List,
  Modal,
  Space,
  Tag,
  Typography,
} from 'antd'
import { HistoryOutlined, RobotOutlined, SendOutlined } from '@ant-design/icons'
import {
  errMsg,
  getStageHistory,
  getStages,
  Job,
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

interface Msg {
  role: 'user' | 'ai'
  text: string
}

/**
 * AI 微调对话面板(方案 / 业务流程图 / ER 共用)。
 *
 * - 用一句话描述要对**当前产物**做的改动 → 触发本阶段的 refine 异步任务(全局进度可见);
 * - 完成后回调 onApplied 让所在步骤重新加载内容;
 * - 「历史版本」可查看并回滚到任一快照;
 * - 若上游内容已变化(当前阶段 stale),顶部提示建议先重新生成。
 */
export default function AiRefinePanel({
  projectId,
  stage,
  canWrite,
  disabled,
  stageLabel,
  onApplied,
}: {
  projectId: number
  stage: StageName
  canWrite: boolean
  /** 尚无内容(如未生成方案)时禁用输入。 */
  disabled?: boolean
  stageLabel: string
  onApplied: () => void
}) {
  const { message } = AntApp.useApp()
  const [expanded, setExpanded] = useState(false)
  const [input, setInput] = useState('')
  const [msgs, setMsgs] = useState<Msg[]>([])
  const [stale, setStale] = useState(false)
  const [histOpen, setHistOpen] = useState(false)
  const [hist, setHist] = useState<StageHistoryItem[]>([])
  const [histLoading, setHistLoading] = useState(false)
  const listRef = useRef<HTMLDivElement | null>(null)

  const kind = `${stage}_refine`

  const refreshStages = useCallback(() => {
    getStages(projectId)
      .then((s) => setStale(!!s?.[stage]?.stale))
      .catch(() => {
        /* 忽略:阶段状态获取失败不影响微调 */
      })
  }, [projectId, stage])

  useEffect(() => {
    refreshStages()
  }, [refreshStages])

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

  const { running, start } = useJob(
    projectId,
    kind,
    (job: Job) => {
      setMsgs((m) => [...m, { role: 'ai', text: job.detail || '已按指令完成微调' }])
      onApplied()
      refreshStages()
    },
    (job: Job) => {
      setMsgs((m) => [...m, { role: 'ai', text: `微调失败:${job.error || '未知错误'}` }])
    },
  )

  useEffect(() => {
    const el = listRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [msgs.length, running, expanded])

  function send() {
    const text = input.trim()
    if (!text || running) return
    setMsgs((m) => [...m, { role: 'user', text }])
    setInput('')
    start(() => refineStage(projectId, stage, text)).catch((e) => {
      const msg = errMsg(e)
      message.error(msg)
      setMsgs((m) => [...m, { role: 'ai', text: `未能提交:${msg}` }])
    })
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

  return (
    <Card
      size="small"
      style={{ marginTop: 12 }}
      title={
        <Space>
          <RobotOutlined />
          <span>AI 微调 · {stageLabel}</span>
        </Space>
      }
      extra={
        <Space>
          <Button size="small" icon={<HistoryOutlined />} disabled={disabled} onClick={openHistory}>
            历史版本
          </Button>
          <Button size="small" type="text" onClick={() => setExpanded((v) => !v)}>
            {expanded ? '收起' : '展开'}
          </Button>
        </Space>
      }
    >
      {!expanded ? (
        <Typography.Text type="secondary">
          用一句话描述要改的地方(如「把合同表的用款金额改成两位小数」「在流程图里补充审批环节」),
          AI 会在当前{stageLabel}上做**最小改动**,并保留历史版本可回滚。
        </Typography.Text>
      ) : (
        <div className="ai-refine">
          {stale ? (
            <Alert
              type="warning"
              showIcon
              style={{ marginBottom: 10 }}
              message="上游内容已更新,当前内容可能已过期"
              description={`建议先重新生成${stageLabel},再做微调,以免与上游不一致。`}
            />
          ) : null}
          <div className="ai-refine-log" ref={listRef}>
            {msgs.length ? (
              msgs.map((m, i) => (
                <div key={i} className={`ai-refine-msg is-${m.role}`}>
                  {m.text}
                </div>
              ))
            ) : (
              <Typography.Text type="secondary">
                例如:「给客户表增加一个『客户等级』下拉字段」「把流程图里门店模块的流程顺序改为先审后批」。
              </Typography.Text>
            )}
          </div>
          <div className="ai-refine-input">
            <Input.TextArea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder={`描述对${stageLabel}的修改(回车发送,Shift+回车换行)`}
              autoSize={{ minRows: 1, maxRows: 4 }}
              disabled={!canWrite || disabled || running}
              onPressEnter={(e) => {
                // 中文输入法选词时回车不应触发发送(等候选词确认)
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
              loading={running}
              disabled={!canWrite || disabled || running || !input.trim()}
              onClick={send}
            >
              发送
            </Button>
          </div>
          {running ? (
            <Typography.Text type="secondary">AI 正在按指令微调,进度见右侧「生成进度」…</Typography.Text>
          ) : null}
          {!canWrite ? <Typography.Text type="secondary">无写入权限</Typography.Text> : null}
        </div>
      )}

      <Modal
        open={histOpen}
        onCancel={() => setHistOpen(false)}
        footer={null}
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
    </Card>
  )
}
