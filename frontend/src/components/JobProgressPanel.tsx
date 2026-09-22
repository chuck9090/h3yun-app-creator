import { useEffect, useRef } from 'react'
import { Alert, Card, Progress, Space, Tag, Timeline, Typography } from 'antd'
import { Job, JobProgressItem } from '../api/client'

const LEVEL_COLOR: Record<string, string> = {
  info: 'blue',
  success: 'green',
  warning: 'orange',
  error: 'red',
}

function statusMeta(job: Job) {
  if (job.status === 'running') return { color: 'processing', text: '处理中' }
  if (job.status === 'done') return { color: 'success', text: '已完成' }
  return { color: 'error', text: '失败' }
}

function lastPct(job: Job): number | undefined {
  for (let i = job.progress.length - 1; i >= 0; i--) {
    const p = job.progress[i].pct
    if (typeof p === 'number') return p
  }
  return undefined
}

function parseTime(s: string): number {
  if (!s) return 0
  const t = new Date(s.replace(' ', 'T')).getTime()
  return Number.isNaN(t) ? 0 : t
}

/** 进度明细里只显示时分秒(完整时间放 title);同一次任务都在同一天,日期冗余且占宽。 */
function shortTime(s: string): string {
  const t = (s || '').trim()
  const m = t.match(/\d{4}-\d{2}-\d{2}\s+(\d{2}:\d{2}:\d{2})/)
  return m ? m[1] : t
}

function elapsed(job: Job): string {
  const start = parseTime(job.createdAt)
  if (!start) return ''
  const end = job.status === 'running' ? Date.now() : parseTime(job.updatedAt) || Date.now()
  const sec = Math.max(0, Math.round((end - start) / 1000))
  return sec < 60 ? `${sec} 秒` : `${Math.floor(sec / 60)} 分 ${sec % 60} 秒`
}

/** 异步任务进度明细:标题 + 状态 + 耗时 + 进度条 + 当前步骤 + 逐条明细(实时)。 */
export default function JobProgressPanel({
  job,
  className,
}: {
  job: Job | null
  className?: string
}) {
  const listRef = useRef<HTMLDivElement | null>(null)
  const count = job?.progress?.length || 0

  // 有新进度时滚到底部,让"当前在做什么"始终可见
  useEffect(() => {
    const el = listRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [count, job?.status])

  if (!job) return null
  const meta = statusMeta(job)
  const running = job.status === 'running'
  const pct = running ? lastPct(job) ?? 0 : 100
  const last = job.progress?.[job.progress.length - 1]
  const items = (job.progress || []).map((p: JobProgressItem, i: number) => ({
    key: i,
    color: LEVEL_COLOR[p.level] || 'gray',
    children: (
      <div className="job-line">
        <span className="job-line-text">{p.text}</span>
        <span className="job-line-meta">
          {typeof p.pct === 'number' ? (
            <span className="job-line-pct">{p.pct}%</span>
          ) : null}
          <span className="job-line-ts" title={p.ts}>
            {shortTime(p.ts)}
          </span>
        </span>
      </div>
    ),
  }))

  return (
    <Card
      size="small"
      className={className}
      style={{ marginBottom: 12 }}
      title={
        <Space wrap size={6}>
          <span>{job.title || job.kind}</span>
          <Tag color={meta.color}>{meta.text}</Tag>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            耗时 {elapsed(job)}
            {count ? ` · 第 ${count} 步` : ''}
          </Typography.Text>
        </Space>
      }
    >
      <Progress
        percent={pct}
        status={job.status === 'failed' ? 'exception' : running ? 'active' : 'success'}
      />
      {running && last ? (
        <div className="job-current">
          <Typography.Text strong>{last.text}</Typography.Text>
        </div>
      ) : null}
      {job.error ? (
        <Alert
          type="error"
          showIcon
          style={{ marginTop: 8 }}
          message="任务失败"
          description={job.error}
        />
      ) : null}
      {items.length ? (
        <div ref={listRef} className="job-list">
          <Timeline items={items} />
        </div>
      ) : null}
    </Card>
  )
}
