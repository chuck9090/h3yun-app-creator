import { useEffect, useRef, useState } from 'react'
import type { PointerEvent as RPointerEvent } from 'react'
import { Alert, App as AntApp, Button, Card, Empty, Modal, Space, Spin, Tag, Tooltip } from 'antd'
import {
  ArrowLeftOutlined,
  CompressOutlined,
  DownloadOutlined,
  FullscreenExitOutlined,
  FullscreenOutlined,
  MinusOutlined,
  OneToOneOutlined,
  PlusOutlined,
  ReloadOutlined,
  RobotOutlined,
} from '@ant-design/icons'
import DOMPurify from 'dompurify'
import { errMsg, get, post } from '../api/client'
import { useJob } from '../hooks/useJob'
import AiRefinePanel from './AiRefinePanel'

/** 对后端渲染的 SVG 再做一次白名单净化(XSS 纵深防御)。 */
function sanitizeSvg(svg: string): string {
  return DOMPurify.sanitize(svg, {
    USE_PROFILES: { svg: true, svgFilters: true, html: true },
  })
}

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
  const [source, setSource] = useState('')
  const [provider, setProvider] = useState('')
  const [loading, setLoading] = useState(true)
  // 分区泳道式 SVG:由后端确定性渲染器产出(services/flowchart_svg.py)
  const [svg, setSvg] = useState('')
  const [svgLoading, setSvgLoading] = useState(false)
  const [svgError, setSvgError] = useState('')
  const [fullscreen, setFullscreen] = useState(false)
  const [zoom, setZoom] = useState(1)
  // 固定视口高度:进入页面时按容器位置算一次(并随窗口尺寸变化重算),
  // 之后缩放只改变图片尺寸、容器高度不变 → 出现横/竖滚动条,而不是把区域撑大或缩小。
  const [viewH, setViewH] = useState<number | undefined>(undefined)
  const viewRef = useRef<HTMLDivElement | null>(null)
  const modalRef = useRef<HTMLDivElement | null>(null)
  const wrapRef = useRef<HTMLDivElement | null>(null)
  // 「适配」去重键:同一张图不重复重置缩放
  const lastFitKey = useRef('')
  // 缩放值的即时镜像:滚轮缩放需要同步读取当前值（state 更新是异步的）
  const zoomRef = useRef(1)
  useEffect(() => {
    zoomRef.current = zoom
  }, [zoom])

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

  // 拉取分区泳道式 SVG(后端自研渲染器,确定性、零 LLM)
  useEffect(() => {
    if (!source.trim()) {
      setSvg('')
      setSvgError('')
      return
    }
    let alive = true
    setSvgLoading(true)
    setSvgError('')
    fetch(`/api/projects/${projectId}/flowchart/svg`, { credentials: 'include' })
      .then(async (r) => {
        if (!r.ok) throw new Error((await r.text()) || `HTTP ${r.status}`)
        return r.text()
      })
      .then((t) => {
        if (alive) setSvg(sanitizeSvg(t))
      })
      .catch((e) => {
        if (alive) {
          setSvg('')
          setSvgError(String(e?.message || e))
        }
      })
      .finally(() => {
        if (alive) setSvgLoading(false)
      })
    return () => {
      alive = false
    }
  }, [source, projectId])

  /** 下载流程图 PNG:前端把当前 SVG 栅格化到 canvas 再导出(不依赖后端依赖)。 */
  async function downloadPng() {
    const el = (viewRef.current?.querySelector('svg') ||
      modalRef.current?.querySelector('svg')) as SVGSVGElement | null
    if (!el) {
      message.error('暂无可导出的流程图')
      return
    }
    try {
      const { w, h } = svgNaturalSize(el)
      const scale = 2
      const clone = el.cloneNode(true) as SVGSVGElement
      clone.setAttribute('xmlns', 'http://www.w3.org/2000/svg')
      clone.setAttribute('width', String(w))
      clone.setAttribute('height', String(h))
      const xml = new XMLSerializer().serializeToString(clone)
      const url = URL.createObjectURL(new Blob([xml], { type: 'image/svg+xml;charset=utf-8' }))
      const img = new Image()
      await new Promise((resolve, reject) => {
        img.onload = () => resolve(null)
        img.onerror = () => reject(new Error('SVG 转换失败'))
        img.src = url
      })
      const canvas = document.createElement('canvas')
      canvas.width = Math.round(w * scale)
      canvas.height = Math.round(h * scale)
      const ctx = canvas.getContext('2d')
      if (!ctx) throw new Error('无法创建画布')
      ctx.fillStyle = '#ffffff'
      ctx.fillRect(0, 0, canvas.width, canvas.height)
      ctx.drawImage(img, 0, 0, canvas.width, canvas.height)
      URL.revokeObjectURL(url)
      const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, 'image/png'))
      if (!blob) throw new Error('导出 PNG 失败')
      const pngUrl = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = pngUrl
      a.download = '业务流程图.png'
      document.body.appendChild(a)
      a.click()
      a.remove()
      URL.revokeObjectURL(pngUrl)
    } catch (e) {
      message.error(errMsg(e))
    }
  }

  // 固定视口高度:进入页面时量一次容器距视口顶部的位置,算出一个固定高度。
  useEffect(() => {
    function measure() {
      const el = wrapRef.current
      if (!el) return
      const top = el.getBoundingClientRect().top
      const h = Math.max(260, window.innerHeight - top - 24)
      setViewH(h)
    }
    measure()
    window.addEventListener('resize', measure)
    return () => window.removeEventListener('resize', measure)
  }, [loading, gate, source])

  // svg / 缩放 / 全屏切换时,把缩放应用到可见容器
  useEffect(() => {
    applyZoom(viewRef.current, zoom)
    if (fullscreen) applyZoom(modalRef.current, zoom)
  }, [svg, zoom, fullscreen])

  // 滚轮缩放:在图上滚动即放大/缩小,并以**鼠标位置为锚点**(缩放后指针下的内容不跑)。
  // 用原生监听 + passive:false,以便 preventDefault 阻止页面随之滚动。
  useEffect(() => {
    const els = [viewRef.current, modalRef.current].filter(Boolean) as HTMLElement[]
    function onWheel(e: WheelEvent) {
      const container = e.currentTarget as HTMLElement
      const el = container.querySelector('svg') as SVGSVGElement | null
      if (!el) return
      e.preventDefault()
      const cur = zoomRef.current
      const factor = e.deltaY < 0 ? 1.12 : 1 / 1.12
      const nz = Number(clampZoom(cur * factor).toFixed(2))
      if (nz === cur) return
      const rect = container.getBoundingClientRect()
      const px = e.clientX - rect.left // 指针在视口内的偏移
      const py = e.clientY - rect.top
      const cx = (container.scrollLeft + px) / cur // 指针指向的内容坐标
      const cy = (container.scrollTop + py) / cur
      const { w, h } = svgNaturalSize(el)
      // 同步应用尺寸,保证滚动位置按新比例即时计算(不等待 React 重渲染)
      el.style.width = `${Math.round(w * nz)}px`
      el.style.height = `${Math.round(h * nz)}px`
      el.style.maxWidth = 'none'
      zoomRef.current = nz
      setZoom(nz)
      container.scrollLeft = cx * nz - px
      container.scrollTop = cy * nz - py
    }
    els.forEach((el) => el.addEventListener('wheel', onWheel, { passive: false }))
    return () => els.forEach((el) => el.removeEventListener('wheel', onWheel))
  }, [fullscreen, source, loading])

  // 出图 / 切换全屏时,自动适配容器宽度(用 fitKey 去重,避免同图重复重置缩放)。
  useEffect(() => {
    if (!svg) return
    const key = `${svg.length}|${fullscreen}`
    if (key === lastFitKey.current) return
    lastFitKey.current = key
    setZoom(fitZoom())
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [svg, fullscreen])

  // 换图 / 切换全屏时,视图回到左上角(避免停留在上一张图的滚动位置)
  useEffect(() => {
    if (viewRef.current) {
      viewRef.current.scrollLeft = 0
      viewRef.current.scrollTop = 0
    }
    if (modalRef.current) {
      modalRef.current.scrollLeft = 0
      modalRef.current.scrollTop = 0
    }
  }, [svg, fullscreen])

  /** 适配容器宽度(用于「适配」按钮与首次出图)。 */
  function fitZoom(): number {
    const container = fullscreen ? modalRef.current : viewRef.current
    const el = container?.querySelector('svg') as SVGSVGElement | null
    if (!container || !el) return zoom
    const { w } = svgNaturalSize(el)
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

  /** 缩放工具条:竖向浮动按钮组(不占布局空间,浮在图面右上方)。 */
  const zoomBar = (
    <div className="flowchart-zoom-group">
      <Tooltip title="放大" placement="left">
        <Button
          size="small"
          icon={<PlusOutlined />}
          onClick={() => zoomBy(ZOOM_STEP)}
          disabled={zoom >= ZOOM_MAX}
        />
      </Tooltip>
      <span className="flowchart-zoom-pct">{Math.round(zoom * 100)}%</span>
      <Tooltip title="缩小" placement="left">
        <Button
          size="small"
          icon={<MinusOutlined />}
          onClick={() => zoomBy(-ZOOM_STEP)}
          disabled={zoom <= ZOOM_MIN}
        />
      </Tooltip>
      <Tooltip title="适配窗口宽度" placement="left">
        <Button size="small" icon={<CompressOutlined />} onClick={zoomFit} />
      </Tooltip>
      <Tooltip title="实际大小" placement="left">
        <Button
          size="small"
          icon={<OneToOneOutlined />}
          onClick={() => zoomTo(1)}
          disabled={Math.round(zoom * 100) === 100}
        />
      </Tooltip>
    </div>
  )

  return (
    <>
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
            <Button icon={<DownloadOutlined />} onClick={downloadPng}>
              下载 PNG
            </Button>
          ) : null}
          {source ? (
            <Button
              icon={fullscreen ? <FullscreenExitOutlined /> : <FullscreenOutlined />}
              onClick={() => setFullscreen((v) => !v)}
            >
              {fullscreen ? '退出全屏' : '全屏'}
            </Button>
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
          {svgError ? (
            <Alert
              type="error"
              showIcon
              style={{ marginBottom: 12 }}
              message="流程图渲染失败"
              description={svgError}
            />
          ) : null}
          {svgLoading && !svg ? (
            <div style={{ textAlign: 'center', padding: 24 }}>
              <Spin />
            </div>
          ) : null}
          <div className="flowchart-view" ref={wrapRef}>
            {svg ? <div className="flowchart-zoom-float">{zoomBar}</div> : null}
            <div
              className={svgCls}
              ref={viewRef}
              style={viewH ? { height: viewH } : undefined}
              {...panProps}
              dangerouslySetInnerHTML={{ __html: svg }}
            />
          </div>
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
        title={null}
        closable={false}
        width="100vw"
        wrapClassName="h3ac-fs-modal"
        styles={{ body: { padding: 0 } }}
      >
        <div className="h3ac-fs-stage">
          <div className="h3ac-fs-actions">
            {svg ? zoomBar : null}
            <Tooltip title="退出全屏(Esc)">
              <Button
                icon={<FullscreenExitOutlined />}
                onClick={() => setFullscreen(false)}
              />
            </Tooltip>
          </div>
          <div
            className={svgCls}
            ref={modalRef}
            {...panProps}
            dangerouslySetInnerHTML={{ __html: svg }}
          />
        </div>
      </Modal>
      </Card>
      <AiRefinePanel
        projectId={projectId}
        stage="flowchart"
        canWrite={canWrite}
        disabled={!source}
        stageLabel="业务流程图"
        onApplied={load}
      />
    </>
  )
}
