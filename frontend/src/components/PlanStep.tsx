import { useEffect, useState } from 'react'
import { Alert, App as AntApp, Button, Card, Empty, Space, Spin, Tag } from 'antd'
import { EditOutlined, ReloadOutlined, RobotOutlined, SaveOutlined } from '@ant-design/icons'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import MDEditor from '@uiw/react-md-editor'
import { errMsg, get, post, put } from '../api/client'
import { useJob } from '../hooks/useJob'
import { useTheme } from '../theme/ThemeContext'

export default function PlanStep({
  projectId,
  canWrite,
  onGenerated,
}: {
  projectId: number
  canWrite: boolean
  onGenerated?: (key: string) => void
}) {
  const { message } = AntApp.useApp()
  const { dark } = useTheme()
  const [markdown, setMarkdown] = useState('')
  const [provider, setProvider] = useState('')
  const [loading, setLoading] = useState(true)
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState('')

  async function load() {
    setLoading(true)
    try {
      const r = await get<{ markdown?: string; provider?: string }>(`/api/projects/${projectId}/plan`)
      setMarkdown(r?.markdown || '')
      setProvider(r?.provider || '')
    } catch (e) {
      message.error(errMsg(e))
    } finally {
      setLoading(false)
    }
  }

  // 异步任务:切页/刷新后仍能恢复「处理中」并展示进度明细
  const { running, start } = useJob(
    projectId,
    'plan',
    async () => {
      await load()
      message.success('系统设计方案已生成')
      onGenerated?.('plan')
    },
    (j) => message.error(`生成失败:${j.error || '未知错误'}`),
  )

  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId])

  async function generate() {
    try {
      await start(() => post(`/api/projects/${projectId}/plan/generate`, {}))
    } catch (e) {
      message.error(errMsg(e))
    }
  }

  function startEdit() {
    setDraft(markdown)
    setEditing(true)
  }

  async function saveEdit() {
    try {
      await put(`/api/projects/${projectId}/plan`, { markdown: draft })
      setMarkdown(draft)
      setEditing(false)
      message.success('方案已保存')
    } catch (e) {
      message.error(errMsg(e))
    }
  }

  return (
    <Card
      title={
        <Space>
          <span>系统设计方案</span>
          {provider ? <Tag color={provider === 'llm' ? 'green' : 'orange'}>{provider}</Tag> : null}
        </Space>
      }
      extra={
        <Space>
          <Button
            icon={<RobotOutlined />}
            type={markdown ? 'default' : 'primary'}
            loading={running}
            disabled={!canWrite || running}
            onClick={generate}
          >
            {markdown ? '重新生成方案' : '生成方案'}
          </Button>
          <Button icon={<ReloadOutlined />} onClick={load}>
            刷新
          </Button>
          {markdown && !editing ? (
            <Button icon={<EditOutlined />} disabled={!canWrite || running} onClick={startEdit}>
              编辑
            </Button>
          ) : null}
          {editing ? (
            <>
              <Button icon={<SaveOutlined />} type="primary" disabled={running} onClick={saveEdit}>
                保存
              </Button>
              <Button onClick={() => setEditing(false)}>取消</Button>
            </>
          ) : null}
        </Space>
      }
    >
      {loading ? (
        <div style={{ textAlign: 'center', padding: 24 }}>
          <Spin />
        </div>
      ) : editing ? (
        <div data-color-mode={dark ? 'dark' : 'light'}>
          <MDEditor value={draft} onChange={(v) => setDraft(v || '')} height={560} />
        </div>
      ) : markdown ? (
        <>
          {provider === 'heuristic' ? (
            <Alert
              type="info"
              showIcon
              style={{ marginBottom: 12 }}
              message="当前使用启发式生成(未配置 LLM),可到「系统设置」配置大模型以获得更好效果。"
            />
          ) : null}
          <div className="md-body">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{markdown}</ReactMarkdown>
          </div>
        </>
      ) : (
        <Empty description="尚未生成方案,点击右上角「生成方案」">
          <Button
            type="primary"
            icon={<RobotOutlined />}
            loading={running}
            disabled={!canWrite || running}
            onClick={generate}
          >
            生成方案
          </Button>
        </Empty>
      )}
    </Card>
  )
}
