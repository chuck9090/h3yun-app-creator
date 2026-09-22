import { useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import {
  App as AntApp,
  Button,
  Card,
  Space,
  Spin,
  Steps,
  Tabs,
  Tag,
  Tooltip,
  Typography,
} from 'antd'
import {
  ApartmentOutlined,
  ArrowLeftOutlined,
  CloudUploadOutlined,
  DeploymentUnitOutlined,
  FileTextOutlined,
  PartitionOutlined,
  ProfileOutlined,
  ReloadOutlined,
  SettingOutlined,
  TeamOutlined,
} from '@ant-design/icons'
import { errMsg, get, Project, STATUS_META, User } from '../api/client'
import RequirementStep from '../components/RequirementStep'
import PlanStep from '../components/PlanStep'
import FlowchartStep from '../components/FlowchartStep'
import DesignStep from '../components/DesignStep'
import DeployStep from '../components/DeployStep'
import ProjectSettingsModal from '../components/ProjectSettingsModal'
import MembersModal from '../components/MembersModal'
import BackToTop from '../components/BackToTop'
import { JobCenter, JobsProvider, jobPct, useJobs } from '../components/JobCenter'

const STEP_KEYS = ['requirement', 'plan', 'flowchart', 'design', 'deploy']

/** 阶段 → 该阶段的任务类型(用于在步骤标题上显示生成进度百分比)。 */
const STAGE_JOB_KINDS: Record<string, string[]> = {
  plan: ['plan'],
  flowchart: ['flowchart'],
  design: ['design'],
  deploy: ['deploy', 'verify'],
}

const STEP_LABELS: Record<string, string> = {
  requirement: '需求',
  plan: '方案',
  flowchart: '业务流程图',
  design: 'ER 设计',
  deploy: '生成应用',
}

const STEP_ICONS: Record<string, ReactNode> = {
  requirement: <FileTextOutlined />,
  plan: <ProfileOutlined />,
  flowchart: <PartitionOutlined />,
  design: <ApartmentOutlined />,
  deploy: <CloudUploadOutlined />,
}

const STATUS_ORDER = ['draft', 'planned', 'flowcharted', 'designed', 'deployed']

function statusRank(status?: string): number {
  const s = status === 'failed' ? 'designed' : status || 'draft'
  const i = STATUS_ORDER.indexOf(s)
  return i < 0 ? 0 : i
}

export default function ProjectWorkbench({ me }: { me: User }) {
  const { id } = useParams()
  // key=id:切换项目时重建 Provider,清空上一个项目的任务进度
  return (
    <JobsProvider key={id}>
      <WorkbenchInner me={me} />
      <JobCenter />
      <BackToTop />
    </JobsProvider>
  )
}

function WorkbenchInner({ me }: { me: User }) {
  const { id } = useParams()
  const nav = useNavigate()
  const { message } = AntApp.useApp()
  const { jobs } = useJobs()
  const [project, setProject] = useState<Project | null>(null)
  const [loading, setLoading] = useState(true)
  const [active, setActive] = useState('requirement')
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [membersOpen, setMembersOpen] = useState(false)
  const stickyRef = useRef<HTMLDivElement | null>(null)

  // 把吸顶区(项目卡片+步骤条)的高度写入 CSS 变量,供方案目录 / 锚点偏移动态跟随
  useEffect(() => {
    const el = stickyRef.current
    if (!el) return
    const apply = () => {
      document.documentElement.style.setProperty(
        '--workbench-sticky-h',
        `${el.offsetHeight}px`,
      )
    }
    apply()
    let ro: ResizeObserver | null = null
    if (typeof ResizeObserver !== 'undefined') {
      ro = new ResizeObserver(apply)
      ro.observe(el)
    } else {
      window.addEventListener('resize', apply)
    }
    return () => {
      if (ro) ro.disconnect()
      else window.removeEventListener('resize', apply)
      document.documentElement.style.removeProperty('--workbench-sticky-h')
    }
  }, [project])

  async function load() {
    setLoading(true)
    try {
      const p = await get<Project>(`/api/projects/${id}`)
      setProject(p)
    } catch (e) {
      message.error(errMsg(e))
      nav('/projects')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id])

  if (loading) {
    return (
      <div style={{ textAlign: 'center', padding: 40 }}>
        <Spin size="large" />
      </div>
    )
  }
  if (!project) return null

  const canWrite =
    project.canWrite ??
    (me.role === 'admin' ||
      project.ownerId === me.id ||
      project.role === 'designer' ||
      project.role === 'admin')

  const statusMeta = STATUS_META[project.status] || { color: 'default', text: project.status }
  const refreshAndGo = (key: string) => {
    setActive(key)
    load()
  }
  const rank = statusRank(project.status)
  const canManage = me.role === 'admin' || project.ownerId === me.id

  const gates: Record<string, string | undefined> = {
    requirement: undefined,
    plan: undefined,
    flowchart: rank < statusRank('planned') ? '请先完成「方案」阶段' : undefined,
    design: rank < statusRank('flowcharted') ? '请先完成「业务流程图」阶段' : undefined,
    deploy: rank < statusRank('designed') ? '请先完成「ER 设计」阶段' : undefined,
  }

  /** 该阶段任务的进度百分比(运行中的优先),无任务返回 undefined。 */
  const stagePct = (key: string): number | undefined => {
    const kinds = STAGE_JOB_KINDS[key] || []
    let fallback: number | undefined
    for (const k of kinds) {
      const job = jobs[k]
      if (!job) continue
      const p = jobPct(job)
      if (job.status === 'running') return p ?? 0
      if (job.status === 'failed') return undefined
      if (p !== undefined && fallback === undefined) fallback = p
    }
    return fallback
  }

  const stageText = (key: string) => {
    const pct = stagePct(key)
    const wrap = (
      <span>
        {STEP_LABELS[key]}
        {typeof pct === 'number' && pct < 100 ? (
          <Tag color="processing" style={{ marginLeft: 6, marginInlineEnd: 0 }}>
            {pct}%
          </Tag>
        ) : null}
      </span>
    )
    return gates[key] ? <Tooltip title={gates[key]}>{wrap}</Tooltip> : wrap
  }

  const stageTabLabel = (key: string) => (
    <Space size={6}>
      {STEP_ICONS[key]}
      <span>{STEP_LABELS[key]}</span>
    </Space>
  )

  const goStage = (key: string) => {
    if (gates[key]) {
      message.warning(gates[key] as string)
      return
    }
    setActive(key)
  }

  const items = [
    {
      key: 'requirement',
      label: stageTabLabel('requirement'),
      disabled: !!gates.requirement,
      children: <RequirementStep projectId={project.id} canWrite={canWrite} />,
    },
    {
      key: 'plan',
      label: stageTabLabel('plan'),
      disabled: !!gates.plan,
      children: (
        <PlanStep projectId={project.id} canWrite={canWrite} onGenerated={refreshAndGo} />
      ),
    },
    {
      key: 'flowchart',
      label: stageTabLabel('flowchart'),
      disabled: !!gates.flowchart,
      children: (
        <FlowchartStep
          projectId={project.id}
          canWrite={canWrite}
          onGoto={setActive}
          onGenerated={() => refreshAndGo('flowchart')}
          gate={gates.flowchart}
        />
      ),
    },
    {
      key: 'design',
      label: stageTabLabel('design'),
      disabled: !!gates.design,
      children: (
        <DesignStep
          projectId={project.id}
          canWrite={canWrite}
          onGenerated={refreshAndGo}
          gate={gates.design}
        />
      ),
    },
    {
      key: 'deploy',
      label: stageTabLabel('deploy'),
      disabled: !!gates.deploy,
      children: (
        <DeployStep
          project={project}
          canWrite={canWrite}
          onDeployed={load}
          gate={gates.deploy}
        />
      ),
    },
  ]

  return (
    <div>
      {/* 项目卡片 + 阶段步骤条:滚动方案等长内容时保持吸顶可见 */}
      <div className="workbench-sticky" ref={stickyRef}>
        <Card className="workbench-hero">
          <div className="hero-main">
            <Button className="hero-back" icon={<ArrowLeftOutlined />} onClick={() => nav('/projects')}>
              返回
            </Button>

            <span className="hero-mark">
              <DeploymentUnitOutlined />
            </span>

          <div className="hero-text">
            <div className="hero-title-row">
              <Typography.Title level={4} className="hero-title">
                {project.title}
              </Typography.Title>
              <Tag color={statusMeta.color}>{statusMeta.text}</Tag>
              {!canWrite ? <Tag color="orange">只读</Tag> : null}
            </div>
            <div className="hero-meta">
              <span className="meta-chip">
                <span className="mono">{project.slug}</span>
              </span>
              {project.appCode ? (
                <span className="meta-chip">
                  应用编码 <span className="mono">{project.appCode}</span>
                </span>
              ) : null}
              <span className="meta-chip">
                阶段 {Math.min(rank + 1, STEP_KEYS.length)}/{STEP_KEYS.length}
              </span>
            </div>
          </div>

          <div className="hero-actions">
            {canManage ? (
              <Button size="small" icon={<TeamOutlined />} onClick={() => setMembersOpen(true)}>
                成员授权
              </Button>
            ) : null}
            {canManage ? (
              <Button size="small" icon={<SettingOutlined />} onClick={() => setSettingsOpen(true)}>
                项目设置
              </Button>
            ) : null}
            <Button size="small" icon={<ReloadOutlined />} onClick={load}>
              刷新
            </Button>
            </div>
          </div>
        </Card>

        <div className="stage-rail">
          <Steps
            size="small"
            current={Math.max(0, STEP_KEYS.indexOf(active))}
            onChange={(i) => goStage(STEP_KEYS[i])}
            items={STEP_KEYS.map((key) => ({
              title: stageText(key),
              icon: STEP_ICONS[key],
              disabled: !!gates[key],
            }))}
          />
        </div>
      </div>

      <Tabs
        className="workbench-tabs"
        activeKey={active}
        onChange={goStage}
        items={items}
        tabBarStyle={{ display: 'none' }}
      />

      <ProjectSettingsModal
        open={settingsOpen}
        project={project}
        onClose={() => setSettingsOpen(false)}
        onSaved={load}
      />
      <MembersModal
        open={membersOpen}
        project={project}
        me={me}
        onClose={() => setMembersOpen(false)}
      />
    </div>
  )
}
