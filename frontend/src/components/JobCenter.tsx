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
import { Job } from '../api/client'
import JobProgressPanel from './JobProgressPanel'

/** 任务类型(与后端 kind 对应)的展示名与排序。 */
export const JOB_KIND_ORDER = ['plan', 'flowchart', 'design', 'deploy', 'verify']
export const JOB_KIND_LABEL: Record<string, string> = {
  plan: '方案',
  flowchart: '业务流程图',
  design: 'ER 设计',
  deploy: '生成应用',
  verify: '回读核对',
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
  report: (kind: string, job: Job | null) => void
}

const JobsCtx = createContext<JobsCtxValue>({ jobs: {}, report: () => {} })

export function useJobs(): JobsCtxValue {
  return useContext(JobsCtx)
}

/** 供各阶段(useJob)上报任务状态;仅关键字段变化时才更新,避免每次轮询全树重渲染。 */
function sameJob(a: Job | undefined, b: Job | null): boolean {
  if (!a || !b) return false
  if (a.id !== b.id || a.status !== b.status || a.updatedAt !== b.updatedAt) return false
  if (a.progress.length !== b.progress.length) return false
  return true
}

export function JobsProvider({ children }: { children: ReactNode }) {
  const [jobs, setJobs] = useState<Record<string, Job>>({})
  const report = useCallback((kind: string, job: Job | null) => {
    setJobs((prev) => {
      if (!job) {
        if (!(kind in prev)) return prev
        const next = { ...prev }
        delete next[kind]
        return next
      }
      if (sameJob(prev[kind], job)) return prev
      return { ...prev, [kind]: job }
    })
  }, [])
  const value = useMemo(() => ({ jobs, report }), [jobs, report])
  return <JobsCtx.Provider value={value}>{children}</JobsCtx.Provider>
}

/**
 * 任务进度中心(右侧边栏)。
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

  if (!list.length) return null

  // 悬浮图标的百分比只反映**运行中**任务(避免已完成任务的 100% 盖住进行中进度)
  const maxPct = running.reduce((m, j) => Math.max(m, jobPct(j) ?? 0), 0)
  const title = list.length === 1 ? JOB_KIND_LABEL[list[0].kind] || '生成进度' : '生成进度'

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
          <JobProgressPanel key={j.kind} job={j} />
        ))}
        <Typography.Paragraph type="secondary" style={{ fontSize: 12, marginTop: 4 }}>
          关闭此面板后,右下角会保留一个悬浮图标,可随时重新打开。
        </Typography.Paragraph>
      </Drawer>
    </>
  )
}
