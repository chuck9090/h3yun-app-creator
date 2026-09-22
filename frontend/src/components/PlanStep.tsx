import { useEffect, useRef, useState } from 'react'
import { Alert, App as AntApp, Button, Card, Empty, Space, Spin, Tag } from 'antd'
import { EditOutlined, ReloadOutlined, RobotOutlined, SaveOutlined } from '@ant-design/icons'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import MDEditor from '@uiw/react-md-editor'
import { errMsg, get, post, put } from '../api/client'
import { useJob } from '../hooks/useJob'
import { useTheme } from '../theme/ThemeContext'

/** 目录项(由正文标题收集而来)。 */
interface TocItem {
  id: string
  level: number
  text: string
}

/** 跳转/高亮的顶部偏移:顶栏高度 + 吸顶区(项目卡片+步骤条)高度 + 余量。
 *  吸顶区高度由 ProjectWorkbench 写入 CSS 变量 `--workbench-sticky-h`。 */
const TOC_GAP = 14

function topOffset(): number {
  if (typeof document === 'undefined') return 80
  const cs = getComputedStyle(document.documentElement)
  const header = parseFloat(cs.getPropertyValue('--header-h')) || 52
  const sticky = parseFloat(cs.getPropertyValue('--workbench-sticky-h')) || 0
  return header + sticky + TOC_GAP
}

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
  const [toc, setToc] = useState<TocItem[]>([])
  const [activeId, setActiveId] = useState('')
  const bodyRef = useRef<HTMLDivElement | null>(null)

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

  // 正文渲染后,从 DOM 收集标题(h1~h3)并注入锚点 id;目录与正文因此天然一致
  useEffect(() => {
    if (editing || !markdown) {
      setToc([])
      return
    }
    const root = bodyRef.current
    if (!root) return
    const els = Array.from(root.querySelectorAll<HTMLElement>('h1, h2, h3'))
    const items: TocItem[] = []
    els.forEach((el, i) => {
      const text = (el.textContent || '').trim()
      if (!text) return
      const id = `plan-sec-${i}`
      el.id = id
      items.push({ id, level: Number(el.tagName.slice(1)), text })
    })
    setToc(items)
  }, [markdown, editing])

  // 滚动高亮:取最后一个已滚过阈值线的标题为「当前」
  useEffect(() => {
    if (!toc.length) return
    let raf = 0
    const pick = () => {
      raf = 0
      const off = topOffset()
      let cur = toc[0].id
      for (const it of toc) {
        const el = document.getElementById(it.id)
        if (!el) continue
        // 留 2px 容差:跳转落点恰在阈值线附近时,避免"该标题未高亮"
        if (el.getBoundingClientRect().top <= off + 2) cur = it.id
        else break
      }
      setActiveId(cur)
    }
    const onScroll = () => {
      if (!raf) raf = window.requestAnimationFrame(pick)
    }
    pick()
    window.addEventListener('scroll', onScroll, { passive: true })
    window.addEventListener('resize', onScroll)
    return () => {
      if (raf) window.cancelAnimationFrame(raf)
      window.removeEventListener('scroll', onScroll)
      window.removeEventListener('resize', onScroll)
    }
  }, [toc])

  function jumpTo(id: string) {
    const el = document.getElementById(id)
    if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

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
          <div className="plan-layout">
            {toc.length ? (
              <nav className="plan-toc" aria-label="方案目录">
                <div className="plan-toc-title">目录</div>
                <div className="plan-toc-list">
                  {toc.map((it) => (
                    <button
                      key={it.id}
                      type="button"
                      className={`plan-toc-item lv${it.level}${
                        activeId === it.id ? ' is-active' : ''
                      }`}
                      title={it.text}
                      onClick={() => jumpTo(it.id)}
                    >
                      {it.text}
                    </button>
                  ))}
                </div>
              </nav>
            ) : null}
            <div ref={bodyRef} className="plan-body md-body">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{markdown}</ReactMarkdown>
            </div>
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
