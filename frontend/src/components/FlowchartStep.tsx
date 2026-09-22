import { useEffect, useMemo, useRef, useState } from 'react'
import type { PointerEvent as RPointerEvent } from 'react'
import { Alert, App as AntApp, Button, Card, Empty, Input, Modal, Segmented, Select, Space, Spin, Tag, Tooltip } from 'antd'
import {
  ArrowLeftOutlined,
  CompressOutlined,
  EditOutlined,
  FullscreenExitOutlined,
  FullscreenOutlined,
  MinusOutlined,
  PlusOutlined,
  ReloadOutlined,
  RobotOutlined,
  SaveOutlined,
} from '@ant-design/icons'
import mermaid from 'mermaid'
import DOMPurify from 'dompurify'
import { errMsg, get, post, put } from '../api/client'
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

const MMID_PREFIX = 'h3ac-mermaid-'

/**
 * 清理 mermaid 残留节点。
 *
 * mermaid.render 失败时会往 `document.body` 追加一个 `#d<id>` 容器并在其中渲染
 * 「Syntax error in text / mermaid version …」错误图,**且不会自行清理** ——
 * 不处理就会以"页面背景内容"的形式一直留在页面上(刷新才消失)。
 * 传 id 只清该次;不传则清掉所有历史残留。
 */
function purgeMermaidStray(id?: string) {
  try {
    const sel = id
      ? `[id="d${id}"], [id="i${id}"]`
      : `[id^="d${MMID_PREFIX}"], [id^="i${MMID_PREFIX}"]`
    document.querySelectorAll(sel).forEach((n) => n.remove())
  } catch {
    /* 忽略:清理失败不应影响渲染流程 */
  }
}

let renderSeq = 0

// 缩放范围与步进
const ZOOM_MIN = 0.2
const ZOOM_MAX = 3
const ZOOM_STEP = 0.1

/** 读取 svg 的自然尺寸(优先 viewBox,其次 width/height 属性)。 */
function svgNaturalSize(svg: SVGSVGElement): { w: number; h: number } {
  const vb = svg.getAttribute('viewBox')
  if (vb) {
    const p = vb.split(/[\s,]+/).map(Number)
    if (p.length === 4 && p[2] > 0 && p[3] > 0) return { w: p[2], h: p[3] }
  }
  const w = parseFloat(svg.getAttribute('width') || '')
  const h = parseFloat(svg.getAttribute('height') || '')
  return { w: w > 0 ? w : 800, h: h > 0 ? h : 600 }
}

/** 按缩放比例设置容器内 svg 的显示宽高(保留自然比例)。 */
function applyZoom(container: HTMLElement | null, zoom: number) {
  if (!container) return
  const svg = container.querySelector('svg') as SVGSVGElement | null
  if (!svg) return
  const { w, h } = svgNaturalSize(svg)
  svg.style.width = `${Math.round(w * zoom)}px`
  svg.style.height = `${Math.round(h * zoom)}px`
  svg.style.maxWidth = 'none'
}

const clampZoom = (z: number) => Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, z))

/** 从 mermaid 源码中拆出模块(subgraph)与公共部分。
 *
 * 生成器按模块输出 `subgraph ModN["模块名"] … end`;把每个模块单独成图,
 * 即可避免 mermaid 对无连接 subgraph 的纵向堆叠(整图又高又窄、看不清)。
 * 非 subgraph 的行(跨模块边等)归入 shared,只在「全部」视图里出现。
 */
interface MmdModule {
  id: string
  name: string
  body: string[] // 含 subgraph 头与 end
}
function splitMmdByModule(src: string): { header: string; modules: MmdModule[]; shared: string[] } {
  const lines = (src || '').split('\n')
  const header: string[] = []
  const shared: string[] = []
  const modules: MmdModule[] = []
  let cur: MmdModule | null = null
  let inSharedHead = true
  for (const ln of lines) {
    const m = ln.match(/^\s*subgraph\s+(\S+?)\s*\[\s*"?([^"\]]*)"?\s*\]/)
    if (m) {
      cur = { id: m[1], name: (m[2] || m[1]).trim(), body: [ln] }
      modules.push(cur)
      inSharedHead = false
      continue
    }
    if (cur) {
      cur.body.push(ln)
      if (/^\s*end\s*$/.test(ln)) cur = null
      continue
    }
    if (inSharedHead) header.push(ln)
    else if (ln.trim()) shared.push(ln)
  }
  const head = (header.find((l) => /^\s*(flowchart|graph)\b/i.test(l)) || 'flowchart LR').trim()
  return { header: head, modules, shared }
}

/** 某个模块单独成图的 mermaid 源码。
 *  强制子图内 `direction LR`:模块内是一条线性链,横向展开矮而宽(约 120px 高),
 *  配合「适配宽度」正好铺满面板;若沿用子图默认的纵向会高达上千像素。 */
function moduleMmd(header: string, mod: MmdModule): string {
  const body = mod.body.filter((l) => !/^\s*direction\s+/i.test(l))
  // 在 subgraph 头之后插入 direction LR
  return [header, body[0], '    direction LR', ...body.slice(1)].join('\n')
}

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
  const [zoom, setZoom] = useState(1)
  const [viewMode, setViewMode] = useState<'all' | 'module'>('all')
  const [activeModule, setActiveModule] = useState('')
  const viewRef = useRef<HTMLDivElement | null>(null)
  const modalRef = useRef<HTMLDivElement | null>(null)
  // 「适配」去重键:同一张图(svg 因主题等重渲染)不重复重置缩放
  const lastFitKey = useRef('')

  // ---------------------------------------------------------------- 拖动平移
  // 流程图常比容器宽/高,光靠滚动条很难看全 → 支持「按住图面拖动」平移(常规交互)。
  const [panning, setPanning] = useState(false)
  const pan = useRef({ active: false, x: 0, y: 0, sl: 0, st: 0 })

  function panDown(e: RPointerEvent<HTMLDivElement>) {
    if (e.button !== 0) return // 仅左键
    if (!e.isPrimary) return // 多点触控:只认主指针,避免第二根手指打断
    const t = e.target as Element | null
    // 点到链接/按钮/输入等交互元素时,不拦截
    if (t && typeof t.closest === 'function' && t.closest('a, button, input, textarea, select')) {
      return
    }
    const el = e.currentTarget
    pan.current = { active: true, x: e.clientX, y: e.clientY, sl: el.scrollLeft, st: el.scrollTop }
    try {
      el.setPointerCapture(e.pointerId) // 指针移出容器也能继续平移
    } catch {
      /* 忽略:个别环境不支持指针捕获 */
    }
    setPanning(true)
  }

  function panMove(e: RPointerEvent<HTMLDivElement>) {
    const s = pan.current
    if (!s.active) return
    const el = e.currentTarget
    el.scrollLeft = s.sl - (e.clientX - s.x)
    el.scrollTop = s.st - (e.clientY - s.y)
  }

  function panEnd(e: RPointerEvent<HTMLDivElement>) {
    if (!pan.current.active) return
    pan.current.active = false
    try {
      e.currentTarget.releasePointerCapture(e.pointerId)
    } catch {
      /* 忽略 */
    }
    setPanning(false)
  }

  const panProps = {
    onPointerDown: panDown,
    onPointerMove: panMove,
    onPointerUp: panEnd,
    onPointerCancel: panEnd,
  }
  const svgCls = `flowchart-svg${panning ? ' is-panning' : ''}`

  const parsed = useMemo(() => splitMmdByModule(source), [source])
  const modules = parsed.modules

  // 未手动选择时,默认选中第一个模块
  const curModule =
    modules.find((m) => m.id === activeModule) || (modules.length ? modules[0] : null)

  // 实际参与渲染的 mermaid 源码:全部视图=原源码;模块视图=该模块单独成图
  const renderSource =
    viewMode === 'module' && curModule ? moduleMmd(parsed.header, curModule) : source

  // 首次拿到多模块源码时默认进「按模块」视图;之后不再覆盖用户的选择
  const viewInit = useRef('')
  useEffect(() => {
    if (!source) return
    if (viewInit.current === source) return
    viewInit.current = source
    setViewMode(modules.length > 1 ? 'module' : 'all')
    setActiveModule('')
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [source, modules.length])

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

  const { running, start } = useJob(
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
    // 清掉历史失败留下的错误图(可能来自上次失败的渲染 / 之前的页面状态)
    purgeMermaidStray()
    if (!renderSource.trim()) {
      setSvg('')
      setRenderError('')
      return
    }
    let alive = true
    const id = `${MMID_PREFIX}${Date.now()}-${renderSeq++}`
    ;(async () => {
      // 1) 先做语法校验:`mermaid.parse` 失败**不会**产生 DOM 残留,
      //    而 `mermaid.render` 失败会往 body 塞错误图 —— 故先 parse,失败即止。
      try {
        await mermaid.parse(renderSource)
      } catch (e: any) {
        if (!alive) return
        setSvg('')
        setRenderError(String(e?.message || e))
        purgeMermaidStray(id)
        return
      }
      // 2) 校验通过后再渲染
      try {
        const res = await mermaid.render(id, renderSource)
        if (!alive) return
        setSvg(sanitizeSvg(res.svg))
        setRenderError('')
      } catch (e: any) {
        if (!alive) return
        setSvg('')
        setRenderError(String(e?.message || e))
        purgeMermaidStray(id)
      }
    })()
    return () => {
      alive = false
      purgeMermaidStray(id)
    }
  }, [renderSource, dark])

  // svg / 缩放 / 全屏切换时,把缩放应用到可见容器
  useEffect(() => {
    applyZoom(viewRef.current, zoom)
    if (fullscreen) applyZoom(modalRef.current, zoom)
  }, [svg, zoom, fullscreen])

  // 出图 / 切换模块 / 切换全屏时,自动适配容器宽度。
  // 依赖含 `svg`:mermaid.render 是异步的,若只依赖 renderSource,effect 会在
  // 新 svg 尚未就绪(还是旧值/空)时提前返回、之后不再触发 → 永远不自动适配。
  // 用 fitKey 去重:仅主题切换等"同一张图的重渲染"不重置用户的缩放。
  useEffect(() => {
    if (!svg) return
    const key = `${renderSource}|${fullscreen}`
    if (key === lastFitKey.current) return
    lastFitKey.current = key
    setZoom(fitZoom())
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [svg, renderSource, fullscreen])

  // 换图 / 换模块 / 切换全屏时,视图回到左上角(避免停留在上一张图的滚动位置)
  useEffect(() => {
    if (viewRef.current) {
      viewRef.current.scrollLeft = 0
      viewRef.current.scrollTop = 0
    }
    if (modalRef.current) {
      modalRef.current.scrollLeft = 0
      modalRef.current.scrollTop = 0
    }
  }, [renderSource, fullscreen])

  /** 适配容器宽度(用于「适配」按钮与首次出图)。 */
  function fitZoom(): number {
    const container = fullscreen ? modalRef.current : viewRef.current
    const svg = container?.querySelector('svg') as SVGSVGElement | null
    if (!container || !svg) return zoom
    const { w } = svgNaturalSize(svg)
    const avail = container.clientWidth - 8
    if (w <= 0 || avail <= 0) return zoom
    return Number(clampZoom(avail / w).toFixed(2))
  }

  /** 缩放操作(手动)。 */
  function zoomBy(delta: number) {
    setZoom((z) => Number(clampZoom(z + delta).toFixed(2)))
  }

  function zoomTo(z: number) {
    setZoom(Number(clampZoom(z).toFixed(2)))
  }

  function zoomFit() {
    setZoom(fitZoom())
  }

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

  /** 缩放工具条(普通视图与全屏共用)。 */
  const zoomBar = (
    <Space size={4}>
      <Tooltip title="缩小">
        <Button
          size="small"
          icon={<MinusOutlined />}
          onClick={() => zoomBy(-ZOOM_STEP)}
          disabled={zoom <= ZOOM_MIN}
        />
      </Tooltip>
      <span className="flowchart-zoom-pct">{Math.round(zoom * 100)}%</span>
      <Tooltip title="放大">
        <Button
          size="small"
          icon={<PlusOutlined />}
          onClick={() => zoomBy(ZOOM_STEP)}
          disabled={zoom >= ZOOM_MAX}
        />
      </Tooltip>
      <Tooltip title="适配窗口宽度">
        <Button size="small" icon={<CompressOutlined />} onClick={zoomFit} />
      </Tooltip>
      <Button size="small" onClick={() => zoomTo(1)} disabled={Math.round(zoom * 100) === 100}>
        100%
      </Button>
    </Space>
  )

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
            <>
              {svg ? (
                <div className="flowchart-toolbar">
                  {modules.length > 1 ? (
                    <Space size={4} className="flowchart-mode">
                      <Segmented
                        size="small"
                        value={viewMode}
                        onChange={(v) => setViewMode(v as 'all' | 'module')}
                        options={[
                          { label: '按模块', value: 'module' },
                          { label: '全部', value: 'all' },
                        ]}
                      />
                      {viewMode === 'module' ? (
                        <Select
                          size="small"
                          style={{ minWidth: 160 }}
                          value={curModule?.id}
                          onChange={(v) => setActiveModule(v)}
                          options={modules.map((m) => ({ value: m.id, label: m.name }))}
                        />
                      ) : null}
                    </Space>
                  ) : null}
                  <div style={{ flex: 1 }} />
                  <span className="flowchart-hint">按住图面可拖动查看</span>
                  {zoomBar}
                </div>
              ) : null}
              <div
                className={svgCls}
                ref={viewRef}
                title="按住可拖动查看"
                {...panProps}
                dangerouslySetInnerHTML={{ __html: svg }}
              />
            </>
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
        <Space style={{ marginBottom: 12 }} wrap>
          <Button icon={<FullscreenExitOutlined />} onClick={() => setFullscreen(false)}>
            退出全屏
          </Button>
          {!editing && svg ? zoomBar : null}
        </Space>
        <div className="flowchart-fullscreen">
          {editing ? (
            <Input.TextArea
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              style={{ height: '100%', fontFamily: 'Consolas, Monaco, monospace' }}
            />
          ) : (
            <div
              className={svgCls}
              ref={modalRef}
              title="按住可拖动查看"
              {...panProps}
              dangerouslySetInnerHTML={{ __html: svg }}
            />
          )}
        </div>
      </Modal>
    </Card>
  )
}
