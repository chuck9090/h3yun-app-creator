import { useEffect, useState } from 'react'
import { Alert, App as AntApp, Button, Card, Empty, Input, Modal, Space, Spin, Tag } from 'antd'
import {
  ArrowLeftOutlined,
  EditOutlined,
  FullscreenExitOutlined,
  FullscreenOutlined,
  ReloadOutlined,
  RobotOutlined,
  SaveOutlined,
} from '@ant-design/icons'
import mermaid from 'mermaid'
import DOMPurify from 'dompurify'
import { errMsg, get, post, put } from '../api/client'
import JobProgressPanel from './JobProgressPanel'
import { useJob } from '../hooks/useJob'
import { useTheme } from '../theme/ThemeContext'

/**
 * mermaid 配置。
 *  - htmlLabels: false —— **必须放在全局**(mermaid 11 已废弃 `flowchart.htmlLabels`,
 *    放在 flowchart 下不生效)。设为全局 false 后,节点文字渲染为 SVG `<text>`,
 *    mermaid 不再生成 `<foreignObject>`;否则 DOMPurify 二次净化会清空
 *    `<foreignObject>` 内的 XHTML(命名空间不兼容),表现为"只有框、没有文字"。
 *  - flowchart.useMaxWidth: false —— 保留图的自然尺寸,避免超宽流程图被 max-width
 *    压得看不清;容器改为横向滚动。
 */
const MERMAID_CFG = {
  startOnLoad: false,
  securityLevel: 'strict' as const,
  htmlLabels: false,
  fontFamily: 'inherit',
  flowchart: { useMaxWidth: false },
}

mermaid.initialize(MERMAID_CFG)

/** 对 mermaid 产出的 SVG 再做一次白名单净化(XSS 双保险)。
 *
 * 依赖上面的全局 `htmlLabels:false`(节点文字走 SVG `<text>`,无 `<foreignObject>`)。
 * 注意:DOMPurify 出于防 mXSS 的考虑,**无法**保留 `<foreignObject>` 内的 XHTML
 * (命名空间不兼容),即使覆盖 `FORBID_CONTENTS`/`ADD_TAGS` 也会清空其子内容 —— 故
 * 切勿把 `htmlLabels` 改回 true,否则文字会再次丢失。
 */
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
  onGenerated,
  gate,
}: {
  projectId: number
  canWrite: boolean
  onGoto?: (key: string) => void
  /** 生成完成后回调:用于让工作台上层重新拉取项目状态,解锁后续阶段 */
  onGenerated?: () => void
  gate?: string
}) {
  const { message } = AntApp.useApp()
  const { dark } = useTheme()
  const [source, setSource] = useState('')
  const [provider, setProvider] = useState('')
  const [loading, setLoading] = useState(true)
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState('')
  const [svg, setSvg] = useState('')
  const [renderError, setRenderError] = useState('')
  const [fullscreen, setFullscreen] = useState(false)

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

  const { job, running, start } = useJob(
    projectId,
    'flowchart',
    async () => {
      await load()
      message.success('业务流程图已生成')
      onGenerated?.()
    },
    (j) => message.error(`生成失败:${j.error || '未知错误'}`),
  )

  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId])

  useEffect(() => {
    // 重新初始化 mermaid,使图表配色跟随当前主题
    mermaid.initialize({ ...MERMAID_CFG, theme: dark ? 'dark' : 'default' })
    if (!source.trim()) {
      setSvg('')
      setRenderError('')
      return
    }
    let alive = true
    const id = `h3ac-mermaid-${Date.now()}-${renderSeq++}`
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
  }, [source, dark])

  async function generate() {
    try {
      await start(() => post(`/api/projects/${projectId}/flowchart/generate`, {}))
    } catch (e) {
      message.error(errMsg(e))
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
      message.success('业务流程图已保存')
      onGenerated?.()
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
            loading={running}
            disabled={!canWrite || !!gate || running}
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
          {source ? (
            <Button
              icon={fullscreen ? <FullscreenExitOutlined /> : <FullscreenOutlined />}
              onClick={() => setFullscreen((v) => !v)}
            >
              {fullscreen ? '退出全屏' : '全屏'}
            </Button>
          ) : null}
          {source && !editing ? (
            <Button icon={<EditOutlined />} disabled={!canWrite || running} onClick={startEdit}>
              编辑源码
            </Button>
          ) : null}
          {editing ? (
            <>
              <Button type="primary" icon={<SaveOutlined />} disabled={running} onClick={saveEdit}>
                保存
              </Button>
              <Button onClick={() => setEditing(false)}>取消</Button>
            </>
          ) : null}
        </Space>
      }
    >
      <JobProgressPanel job={job} />
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
        <div style={{ textAlign: 'center', padding: 24 }}>
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
            <summary style={{ cursor: 'pointer', color: 'var(--text-3)' }}>查看 / 复制 Mermaid 源码</summary>
            <Input.TextArea
              value={source}
              readOnly
              autoSize={{ minRows: 8, maxRows: 20 }}
              style={{ marginTop: 8, fontFamily: 'Consolas, Monaco, monospace' }}
            />
          </details>
        </>
      ) : (
        <Empty description="尚未生成业务流程图">
          <Space>
            <Button
              type="primary"
              icon={<RobotOutlined />}
              loading={running}
              disabled={!canWrite || !!gate || running}
              onClick={generate}
            >
              生成业务流程图
            </Button>
            {canWrite ? null : <span style={{ color: 'var(--text-3)' }}>无写入权限</span>}
          </Space>
        </Empty>
      )}

      <Modal
        open={fullscreen}
        onCancel={() => setFullscreen(false)}
        footer={null}
        width="90%"
        title="业务流程图"
        styles={{ body: { padding: 16 } }}
      >
        <Space style={{ marginBottom: 12 }}>
          <Button icon={<FullscreenExitOutlined />} onClick={() => setFullscreen(false)}>
            退出全屏
          </Button>
        </Space>
        <div style={{ height: 'calc(100vh - 200px)', overflow: 'auto' }}>
          {editing ? (
            <Input.TextArea
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              style={{ height: '100%', fontFamily: 'Consolas, Monaco, monospace' }}
            />
          ) : (
            <div className="flowchart-svg" dangerouslySetInnerHTML={{ __html: svg }} />
          )}
        </div>
      </Modal>
    </Card>
  )
}
