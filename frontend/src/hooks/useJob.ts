import { useCallback, useEffect, useRef, useState } from 'react'
import { errMsg, getProjectJobs, Job, JobStartResponse } from '../api/client'
import { jobKey, useJobs } from '../components/JobCenter'

export interface UseJobResult {
  job: Job | null
  running: boolean
  error: string
  /** 触发一次异步任务:req 返回后端 {job, created};随后由全局轮询更新到终态。 */
  start: (req: () => Promise<JobStartResponse>) => Promise<void>
  /** 清除本地展示的任务(不影响后端执行)。 */
  clear: () => void
}

/**
 * 异步任务 hook:任务状态托管在**全局** JobsProvider(跨页面持续轮询),
 * 因此切换步骤 / 路由 / 刷新后仍能恢复「处理中」并展示进度明细。
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
  const { jobs, report } = useJobs()
  const key = jobKey(projectId, kind)
  const job = jobs[key] ?? null
  const [error, setError] = useState('')

  const doneRef = useRef(onDone)
  doneRef.current = onDone
  const failedRef = useRef(onFailed)
  failedRef.current = onFailed
  // 已观察到的状态:仅对「本次挂载期间发生的变化」触发回调,避免复查历史任务时误报成功。
  const seenStatus = useRef('')
  // 是否由本组件触发过 start(用于 start 直接返回终态的极端情况)
  const startedHere = useRef(false)
  const restoredKey = useRef('')

  // 恢复:进入项目 / 组件挂载时,若该任务在上下文中尚无记录,则从后端接管运行中的任务。
  // 上下文已有该任务(例如从别的页面切回来,或运行中切页再回来)时直接复用,不覆盖。
  useEffect(() => {
    seenStatus.current = ''
    startedHere.current = false
    if (restoredKey.current === key) return
    restoredKey.current = key
    let alive = true
    getProjectJobs(projectId, true)
      .then((r) => {
        if (!alive) return
        const active = (r?.items || []).find((x) => x.kind === kind)
        if (active) report(key, active)
      })
      .catch(() => {
        /* 忽略:恢复失败不影响正常使用 */
      })
    return () => {
      alive = false
    }
  }, [key, projectId, kind, report])

  // 状态首次进入终态时回调(成功 / 失败各一次)。
  // 仅在「本次挂载期间从 running 变化而来」或「本次 start 触发」时回调,
  // 避免重新进入页面时对历史已完成任务重复弹提示。
  useEffect(() => {
    if (!job) return
    if (seenStatus.current === job.status) return
    const prev = seenStatus.current
    seenStatus.current = job.status
    if (job.status === 'running') return
    if (!(prev === 'running' || startedHere.current)) return
    startedHere.current = false
    if (job.status === 'done') doneRef.current?.(job)
    else if (job.status === 'failed') failedRef.current?.(job)
  }, [job])

  const start = useCallback(
    async (req: () => Promise<JobStartResponse>) => {
      setError('')
      try {
        const r = await req()
        seenStatus.current = ''
        startedHere.current = true
        report(key, r.job)
      } catch (e) {
        setError(errMsg(e))
        throw e
      }
    },
    [key, report],
  )

  const clear = useCallback(() => {
    seenStatus.current = ''
    startedHere.current = false
    setError('')
    report(key, null)
  }, [key, report])

  return { job, running: job?.status === 'running', error, start, clear }
}
