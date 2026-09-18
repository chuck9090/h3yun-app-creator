import { useEffect, useState } from 'react'
import { Alert, App as AntApp, Button, Card, Empty, Input, Space, Spin, Tag } from 'antd'
import {
  ArrowLeftOutlined,
  EditOutlined,
  ReloadOutlined,
  RobotOutlined,
  SaveOutlined,
} from '@ant-design/icons'
import mermaid from 'mermaid'
import DOMPurify from 'dompurify'
import { errMsg, get, post, put } from '../api/client'

mermaid.initialize({ startOnLoad: false, theme: 'default', securityLevel: 'strict', fontFamily: 'inherit' })

/** 对 mermaid 产出的 SVG 再做一次白名单净化(XSS 双保险)。 */
function sanitizeSvg(svg: string): string {
  return DOMPurify.sanitize(svg, {
    USE_PROFILES: { svg: true, svgFilters: true, html: true },
  })
}

let renderSeq = 0

export default function FlowchartStep({
  projectId,
  canWrite,
  onGoto,
  gate,
}: {
  projectId: number
  canWrite: boolean
  onGoto?: (key: string) => void
  gate?: string
}) {
  const { message } = AntApp.useApp()
  const [source, setSource] = useState('')
  const [provider, setProvider] = useState('')
  const [loading, setLoading] = useState(true)
  const [generating, setGenerating] = useState(false)
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState('')
  const [svg, setSvg] = useState('')
  const [renderError, setRenderError] = useState('')

  async function load() {
    setLoading(true)
    try {
      const r = await get<{ mermaid?: string; provider?: string }>(
        `/api/projects/${projectId}/flowchart`,
      )
      setSource(r?.mermaid || '')
      setProvider(r?.provider || '')
    } catch (e) {
      message.error(errMsg(e))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId])

  useEffect(() => {
    if (!source.trim()) {
      setSvg('')
      setRenderError('')
      return
    }
    let alive = true
    const id = `h3f-mermaid-${Date.now()}-${renderSeq++}`
    mermaid
      .render(id, source)
      .then((res) => {
        if (!alive) return
        setSvg(sanitizeSvg(res.svg))
        setRenderError('')
      })
      .catch((e: any) => {
        if (!alive) return
        setSvg('')
        setRenderError(String(e?.message || e))
      })
    return () => {
      alive = false
    }
  }, [source])

  async function generate() {
    setGenerating(true)
    try {
      const r = await post<{ mermaid?: string; provider?: string }>(
        `/api/projects/${projectId}/flowchart/generate`,
        {},
      )
      setSource(r?.mermaid || '')
      setProvider(r?.provider || '')
      message.success('业务流程图已生成')
    } catch (e) {
      message.error(errMsg(e))
    } finally {
      setGenerating(false)
    }
  }

  function startEdit() {
    setDraft(source)
    setEditing(true)
  }

  async function saveEdit() {
    try {
      await put(`/api/projects/${projectId}/flowchart`, { mermaid: draft })
      setSource(draft)
      setEditing(false)
      message.success('流程图已保存')
    } catch (e) {
      message.error(errMsg(e))
    }
  }

  return (
    <Card
      title={
        <Space>
          <span>业务流程图</span>
          {provider ? <Tag color={provider === 'llm' ? 'green' : 'orange'}>{provider}</Tag> : null}
        </Space>
      }
      extra={
        <Space wrap>
          <Button
            type={source ? 'default' : 'primary'}
            icon={<RobotOutlined />}
            loading={generating}
            disabled={!canWrite || !!gate}
            onClick={generate}
          >
            {source ? '重新生成' : '生成业务流程图'}
          </Button>
          <Button icon={<ArrowLeftOutlined />} onClick={() => onGoto?.('plan')}>
            回到方案修改
          </Button>
          <Button icon={<ReloadOutlined />} onClick={load}>
            刷新
          </Button>
          {source && !editing ? (
            <Button icon={<EditOutlined />} disabled={!canWrite} onClick={startEdit}>
              编辑源码
            </Button>
          ) : null}
          {editing ? (
            <>
              <Button type="primary" icon={<SaveOutlined />} onClick={saveEdit}>
                保存
              </Button>
              <Button onClick={() => setEditing(false)}>取消</Button>
            </>
          ) : null}
        </Space>
      }
    >
      {gate ? (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 12 }}
          message="前置条件未满足"
          description={gate}
        />
      ) : null}
      {loading ? (
        <div style={{ textAlign: 'center', padding: 40 }}>
          <Spin />
        </div>
      ) : source ? (
        <>
          {renderError ? (
            <Alert
              type="error"
              showIcon
              style={{ marginBottom: 12 }}
              message="Mermaid 渲染失败"
              description={renderError}
            />
          ) : null}
          {editing ? (
            <Input.TextArea
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              autoSize={{ minRows: 12, maxRows: 24 }}
              style={{ fontFamily: 'Consolas, Monaco, monospace' }}
            />
          ) : (
            <div className="flowchart-svg" dangerouslySetInnerHTML={{ __html: svg }} />
          )}
          <details style={{ marginTop: 12 }}>
            <summary style={{ cursor: 'pointer', color: '#8c8c8c' }}>查看 / 复制 Mermaid 源码</summary>
            <Input.TextArea
              value={source}
              readOnly
              autoSize={{ minRows: 8, maxRows: 20 }}
              style={{ marginTop: 8, fontFamily: 'Consolas, Monaco, monospace' }}
            />
          </details>
        </>
      ) : (
        <Empty description="尚未生成流程图">
          <Space>
            <Button
              type="primary"
              icon={<RobotOutlined />}
              loading={generating}
              disabled={!canWrite || !!gate}
              onClick={generate}
            >
              生成业务流程图
            </Button>
            {canWrite ? null : <span style={{ color: '#8c8c8c' }}>无写入权限</span>}
          </Space>
        </Empty>
      )}
    </Card>
  )
}
