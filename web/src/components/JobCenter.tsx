import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react'
import type { ReactNode } from 'react'
import { Badge, Button, Drawer, Space, Tag, Tooltip, Typography } from 'antd'
import { LoadingOutlined, ProfileOutlined } from '@ant-design/icons'
import { getActiveJobs, getJob, Job } from '../api/client'
import JobProgressPanel from './JobProgressPanel'

/** 任务类型(与后端 kind 对应)的展示名与排序。 */
export const JOB_KIND_ORDER = [
  'plan',
  'plan_refine',
  'flowchart',
  'flowchart_refine',
  'design',
  'design_refine',
  'deploy',
  'verify',
]
export const JOB_KIND_LABEL: Record<string, string> = {
  plan: '方案',
  plan_refine: '方案微调',
  flowchart: '业务流程图',
  flowchart_refine: '流程图微调',
  design: 'ER 设计',
  design_refine: 'ER 微调',
  deploy: '生成应用',
  verify: '回读核对',
}

/** 任务在进度中心里的唯一键:项目 + 类型(全局,跨页面保留)。 */
export function jobKey(projectId: number, kind: string): string {
  return `${projectId}:${kind}`
}

/** 任务进度百分比:运行中取最后一条带 pct 的进度,完成=100,失败=undefined。 */
export function jobPct(job: Job | null | undefined): number | undefined {
  if (!job) return undefined
  if (job.status === 'done') return 100
  if (job.status !== 'running') return undefined
  for (let i = job.progress.length - 1; i >= 0; i--) {
    const p = job.progress[i].pct
    if (typeof p === 'number') return p
  }
  return 0
}

interface JobsCtxValue {
  jobs: Record<string, Job>
  report: (key: string, job: Job | null) => void
}

const JobsCtx = createContext<JobsCtxValue>({ jobs: {}, report: () => {} })

export function useJobs(): JobsCtxValue {
  return useContext(JobsCtx)
}

const POLL_MS = 1200

/**
 * 全局任务状态中心。
 *
 * 任务状态与**轮询统一放在这里**(而不是各阶段组件内),因此:
 *  * 无论用户切到哪个页面,进度都会持续更新;
 *  * 任一页面都能看到右下角的「生成进度」悬浮入口。
 */
export function JobsProvider({ children }: { children: ReactNode }) {
  const [jobs, setJobs] = useState<Record<string, Job>>({})
  const report = useCallback((key: string, job: Job | null) => {
    setJobs((prev) => {
      if (!job) {
        if (!(key in prev)) return prev
        const next = { ...prev }
        delete next[key]
        return next
      }
      const cur = prev[key]
      if (cur && cur.id === job.id && cur.status === job.status &&
          cur.updatedAt === job.updatedAt && cur.progress.length === job.progress.length) {
        return prev
      }
      return { ...prev, [key]: job }
    })
  }, [])

  // 轮询所有「运行中」的任务:与页面无关,切页也继续刷新进度
  const jobsRef = useRef(jobs)
  jobsRef.current = jobs
  const inflight = useRef<Set<number>>(new Set())
  useEffect(() => {
    const timer = window.setInterval(() => {
      const running = Object.entries(jobsRef.current).filter(([, j]) => j.status === 'running')
      for (const [key, j] of running) {
        if (inflight.current.has(j.id)) continue
        inflight.current.add(j.id)
        getJob(j.id)
          .then((nj) => report(key, nj))
          .catch(() => {
            /* 网络抖动忽略,下一轮继续 */
          })
          .finally(() => inflight.current.delete(j.id))
      }
    }, POLL_MS)
    return () => window.clearInterval(timer)
  }, [report])

  // 启动 / 定时「重新发现」运行中任务:刷新页面后上下文虽为空,但后端仍有运行中的任务，
  // 通过全局接口把它们重新纳入列表 → 无论当前在哪个页面,右下角进度入口都会恢复。
  useEffect(() => {
    let alive = true
    const sync = () => {
      getActiveJobs()
        .then((r) => {
          if (!alive) return
          for (const j of r?.items || []) report(jobKey(j.projectId, j.kind), j)
        })
        .catch(() => {
          /* 忽略:未登录/网络抖动 */
        })
    }
    sync()
    const timer = window.setInterval(sync, 4000)
    return () => {
      alive = false
      window.clearInterval(timer)
    }
  }, [report])

  const value = useMemo(() => ({ jobs, report }), [jobs, report])
  return <JobsCtx.Provider value={value}>{children}</JobsCtx.Provider>
}

/**
 * 任务进度中心(右侧边栏 / 右下角悬浮)。全局挂载,任意页面可见。
 * - 详细进度与内容统一收到这里,不再占用阶段内容区(避免遮挡);
 * - 可关闭为右下角悬浮图标;有运行中任务时自动弹出,图标带百分比。
 */
export function JobCenter() {
  const { jobs } = useJobs()
  const [open, setOpen] = useState(false)
  const autoSig = useRef('')

  const list = useMemo(
    () =>
      Object.values(jobs).sort(
        (a, b) =>
          JOB_KIND_ORDER.indexOf(a.kind) - JOB_KIND_ORDER.indexOf(b.kind) ||
          a.id - b.id,
      ),
    [jobs],
  )
  const running = list.filter((j) => j.status === 'running')

  // 有任务「开始运行」或「新失败」时自动弹出一次;用户手动收起后不再强拉
  // (签名只含 kind/id/status,进度追加不会改变它 → 收起后不会反复弹)
  useEffect(() => {
    const sig = list.map((j) => `${j.kind}:${j.id}:${j.status}`).join('|')
    const needAttention = list.some((j) => j.status === 'running' || j.status === 'failed')
    if (needAttention && sig !== autoSig.current) {
      autoSig.current = sig
      setOpen(true)
    }
    if (!needAttention) autoSig.current = ''
  }, [list])

  // 点击抽屉以外的任意位置即自动收起(抽屉本身 mask=false,不遮挡页面,故手动处理)。
  // 用 pointerdown 覆盖鼠标与触屏;点到抽屉内部(含量表/按钮)则不关闭。
  useEffect(() => {
    if (!open) return
    function onDown(e: PointerEvent) {
      const t = e.target as Element | null
      if (t && typeof t.closest === 'function') {
        if (t.closest('.ant-drawer-content') || t.closest('.ant-drawer-mask')) return
      }
      setOpen(false)
    }
    document.addEventListener('pointerdown', onDown, true)
    return () => document.removeEventListener('pointerdown', onDown, true)
  }, [open])

  if (!list.length) return null

  // 悬浮图标的百分比只反映**运行中**任务(避免已完成任务的 100% 盖住进行中进度)
  const maxPct = running.reduce((m, j) => Math.max(m, jobPct(j) ?? 0), 0)
  const title =
    list.length === 1
      ? JOB_KIND_LABEL[list[0].kind] || '生成进度'
      : running.length === 1
        ? JOB_KIND_LABEL[running[0].kind] || '生成进度'
        : '生成进度'

  return (
    <>
      {!open ? (
        <div className="job-fab">
          <Tooltip title={`${title}(点击查看详情)`} placement="left">
            <Badge count={running.length} size="small" offset={[-2, 4]}>
              <Button
                type="primary"
                shape="circle"
                size="large"
                className={running.length ? 'job-fab-btn is-running' : 'job-fab-btn'}
                icon={running.length ? <LoadingOutlined /> : <ProfileOutlined />}
                onClick={() => setOpen(true)}
              />
            </Badge>
          </Tooltip>
          {running.length ? <span className="job-fab-pct">{maxPct}%</span> : null}
        </div>
      ) : null}

      <Drawer
        className="job-drawer"
        placement="right"
        width={460}
        open={open}
        onClose={() => setOpen(false)}
        mask={false}
        maskClosable={false}
        title={
          <Space size={6} wrap>
            <span>生成进度</span>
            {running.length ? (
              <Tag color="processing">进行中 {running.length}</Tag>
            ) : (
              <Tag>已结束</Tag>
            )}
            {running.length ? (
              <Tag color="blue">{maxPct}%</Tag>
            ) : null}
          </Space>
        }
        extra={
          <Tooltip title="收起为悬浮图标">
            <Button type="text" size="small" onClick={() => setOpen(false)}>
              收起
            </Button>
          </Tooltip>
        }
      >
        {list.map((j) => (
          <JobProgressPanel key={`${j.projectId}:${j.kind}:${j.id}`} job={j} />
        ))}
        <Typography.Paragraph type="secondary" style={{ fontSize: 12, marginTop: 4 }}>
          关闭此面板后,右下角会保留一个悬浮图标,可随时重新打开。
        </Typography.Paragraph>
      </Drawer>
    </>
  )
}
