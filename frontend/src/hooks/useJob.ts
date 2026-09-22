import { useCallback, useEffect, useRef, useState } from 'react'
import {
  errMsg,
  getJob,
  getProjectJobs,
  Job,
  JobStartResponse,
} from '../api/client'
import { useJobs } from '../components/JobCenter'

const POLL_MS = 1200

export interface UseJobResult {
  job: Job | null
  running: boolean
  error: string
  /** 触发一次异步任务:req 返回后端 {job, created};随后自动轮询到终态。 */
  start: (req: () => Promise<JobStartResponse>) => Promise<void>
  /** 清除本地展示的任务(不影响后端执行)。 */
  clear: () => void
}

/**
 * 异步任务 hook:把长耗时任务的状态托管到后端(轮询),从而在切换步骤 /
 * 路由 / 刷新后仍能恢复「处理中」并展示进度明细,且运行中不可重复触发。
 *
 * @param projectId 项目 id
 * @param kind      任务类型(plan/flowchart/design/deploy/verify)
 * @param onDone    任务成功回调(通常用于重新加载内容)
 * @param onFailed  任务失败回调
 */
export function useJob(
  projectId: number,
  kind: string,
  onDone?: (job: Job) => void,
  onFailed?: (job: Job) => void,
): UseJobResult {
  const [job, setJob] = useState<Job | null>(null)
  const [error, setError] = useState('')
  // 上报给「任务进度中心」(右侧边栏展示详细进度;阶段标题只显示百分比)
  const { report } = useJobs()
  useEffect(() => {
    report(kind, job)
  }, [kind, job, report])

  const doneRef = useRef(onDone)
  doneRef.current = onDone
  const failedRef = useRef(onFailed)
  failedRef.current = onFailed
  const seenStatus = useRef('')
  // 请求序号:防止「恢复」的迟到响应覆盖「start」刚设的新任务(反之亦然)
  const reqSeq = useRef(0)

  // 恢复:进入项目 / 组件挂载时,若该项目该类型已有运行中的任务,则接管它
  useEffect(() => {
    const my = ++reqSeq.current
    let alive = true
    seenStatus.current = ''
    setJob(null)          // 切换项目时先清空,避免沿用上一个项目的任务
    getProjectJobs(projectId, true)
      .then((r) => {
        if (!alive || reqSeq.current !== my) return
        const active = (r?.items || []).find((x) => x.kind === kind)
        if (active) setJob(active)
      })
      .catch(() => {
        /* 忽略:恢复失败不影响正常使用 */
      })
    return () => {
      alive = false
    }
  }, [projectId, kind])

  const jobId = job?.id
  const jobStatus = job?.status

  // 轮询:仅运行中任务需要定时拉取
  useEffect(() => {
    if (!jobId || jobStatus !== 'running') return
    let alive = true
    const timer = window.setInterval(() => {
      getJob(jobId)
        .then((j) => {
          if (alive) setJob(j)
        })
        .catch(() => {
          /* 网络抖动忽略,下一轮继续 */
        })
    }, POLL_MS)
    return () => {
      alive = false
      window.clearInterval(timer)
    }
  }, [jobId, jobStatus])

  // 状态首次进入终态时回调(成功 / 失败各一次)
  useEffect(() => {
    if (!job) return
    if (seenStatus.current === job.status) return
    const prev = seenStatus.current
    seenStatus.current = job.status
    if (prev === '' && job.status === 'running') return
    if (job.status === 'done') doneRef.current?.(job)
    else if (job.status === 'failed') failedRef.current?.(job)
  }, [job])

  const start = useCallback(async (req: () => Promise<JobStartResponse>) => {
    setError('')
    const my = ++reqSeq.current
    try {
      const r = await req()
      if (reqSeq.current !== my) return
      seenStatus.current = ''
      setJob(r.job)
    } catch (e) {
      setError(errMsg(e))
      throw e
    }
  }, [])

  const clear = useCallback(() => {
    seenStatus.current = ''
    setJob(null)
    setError('')
  }, [])

  return { job, running: job?.status === 'running', error, start, clear }
}
