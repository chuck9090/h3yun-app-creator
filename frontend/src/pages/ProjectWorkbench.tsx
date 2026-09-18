import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { App as AntApp, Card, Space, Spin, Steps, Tabs, Tag, Typography, Button } from 'antd'
import {
  ArrowLeftOutlined,
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

const STEP_KEYS = ['requirement', 'plan', 'flowchart', 'design', 'deploy']

const STATUS_ORDER = ['draft', 'planned', 'flowcharted', 'designed', 'deployed']

function statusRank(status?: string): number {
  const i = STATUS_ORDER.indexOf(status || 'draft')
  return i < 0 ? 0 : i
}

export default function ProjectWorkbench({ me }: { me: User }) {
  const { id } = useParams()
  const nav = useNavigate()
  const { message } = AntApp.useApp()
  const [project, setProject] = useState<Project | null>(null)
  const [loading, setLoading] = useState(true)
  const [active, setActive] = useState('requirement')
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [membersOpen, setMembersOpen] = useState(false)

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
      <div style={{ textAlign: 'center', padding: 60 }}>
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

  const planGate = rank < statusRank('planned') ? '请先在「方案」步骤生成系统设计方案。' : undefined
  const deployGate =
    rank < statusRank('designed') ? '请先在「ER 设计」步骤生成并保存设计方案。' : undefined

  const items = [
    {
      key: 'requirement',
      label: '需求',
      children: <RequirementStep projectId={project.id} canWrite={canWrite} />,
    },
    {
      key: 'plan',
      label: '方案',
      children: (
        <PlanStep projectId={project.id} canWrite={canWrite} onGenerated={refreshAndGo} />
      ),
    },
    {
      key: 'flowchart',
      label: '流程图',
      children: (
        <FlowchartStep
          projectId={project.id}
          canWrite={canWrite}
          onGoto={setActive}
          gate={planGate}
        />
      ),
    },
    {
      key: 'design',
      label: 'ER 设计',
      children: (
        <DesignStep
          projectId={project.id}
          canWrite={canWrite}
          onGenerated={refreshAndGo}
          gate={planGate}
        />
      ),
    },
    {
      key: 'deploy',
      label: '生成应用',
      children: (
        <DeployStep
          project={project}
          canWrite={canWrite}
          onDeployed={load}
          gate={deployGate}
        />
      ),
    },
  ]

  return (
    <div>
      <Card style={{ marginBottom: 16 }}>
        <div className="page-title">
          <Button icon={<ArrowLeftOutlined />} onClick={() => nav('/projects')}>
            返回
          </Button>
          <Typography.Title level={4} style={{ margin: 0 }}>
            {project.title}
          </Typography.Title>
          <Tag color={statusMeta.color}>{statusMeta.text}</Tag>
          {project.appCode ? <Tag>应用编码:{project.appCode}</Tag> : null}
          {!canWrite ? <Tag color="orange">只读</Tag> : null}
          {canManage ? (
            <Button
              size="small"
              icon={<TeamOutlined />}
              style={{ marginLeft: 'auto' }}
              onClick={() => setMembersOpen(true)}
            >
              成员授权
            </Button>
          ) : null}
          {canManage ? (
            <Button
              size="small"
              icon={<SettingOutlined />}
              style={canManage ? undefined : { marginLeft: 'auto' }}
              onClick={() => setSettingsOpen(true)}
            >
              项目设置
            </Button>
          ) : null}
          <Button
            size="small"
            icon={<ReloadOutlined />}
            style={canManage ? undefined : { marginLeft: 'auto' }}
            onClick={load}
          >
            刷新
          </Button>
        </div>
        <Space size="small" wrap>
          <Typography.Text type="secondary">
            项目标识:{project.slug}
          </Typography.Text>
        </Space>
      </Card>

      <div className="workbench-steps">
        <Steps
          size="small"
          current={Math.max(0, STEP_KEYS.indexOf(active))}
          onChange={(i) => setActive(STEP_KEYS[i])}
          items={[
            { title: '需求' },
            { title: '方案' },
            { title: '流程图' },
            { title: 'ER 设计' },
            { title: '生成应用' },
          ]}
        />
      </div>

      <Tabs activeKey={active} onChange={setActive} items={items} />

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
