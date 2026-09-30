import { useCallback, useEffect, useState } from 'react'
import {
  Alert,
  App as AntApp,
  Button,
  Card,
  Descriptions,
  Empty,
  Space,
  Switch,
  Table,
  Tag,
  Typography,
} from 'antd'
import { CloudUploadOutlined, ReloadOutlined, SafetyCertificateOutlined } from '@ant-design/icons'
import {
  CredentialsStatus,
  DeployAutomationResult,
  DeployGroupResult,
  DeployResult,
  DeploySheetResult,
  errMsg,
  get,
  post,
  Project,
} from '../api/client'
import { useJob } from '../hooks/useJob'

function normalizeSheets(res: any): DeploySheetResult[] {
  if (!res) return []
  const list = Array.isArray(res.sheets)
    ? res.sheets
    : Array.isArray(res.written)
      ? res.written
      : Array.isArray(res)
        ? res
        : []
  return list.map((it: any) =>
    typeof it === 'string' ? { key: it, created: true } : (it as DeploySheetResult),
  )
}

function normalizeAutomations(res: any): DeployAutomationResult[] {
  if (!res || !Array.isArray(res.automations)) return []
  return res.automations as DeployAutomationResult[]
}

function normalizeGroups(res: any): DeployGroupResult[] {
  if (!res || !Array.isArray(res.groups)) return []
  return res.groups as DeployGroupResult[]
}

export default function DeployStep({
  project,
  canWrite,
  onDeployed,
  gate,
}: {
  project: Project
  canWrite: boolean
  onDeployed?: () => void
  gate?: string
}) {
  const projectId = project.id
  const { message, modal } = AntApp.useApp()
  const [status, setStatus] = useState<CredentialsStatus | null>(null)
  const [statusLoading, setStatusLoading] = useState(true)
  const [force, setForce] = useState(false)
  const [result, setResult] = useState<DeployResult | null>(null)
  const [sheetRows, setSheetRows] = useState<DeploySheetResult[]>([])
  const [autoRows, setAutoRows] = useState<DeployAutomationResult[]>([])
  const [groupRows, setGroupRows] = useState<DeployGroupResult[]>([])
  const [deployError, setDeployError] = useState('')
  const [verifyResult, setVerifyResult] = useState<any>(null)

  const loadStatus = useCallback(async () => {
    setStatusLoading(true)
    try {
      const s = await get<CredentialsStatus>(`/api/projects/${projectId}/credentials/status`)
      setStatus(s)
    } catch (e) {
      message.error(errMsg(e))
      setStatus(null)
    } finally {
      setStatusLoading(false)
    }
  }, [projectId, message])

  useEffect(() => {
    loadStatus()
  }, [loadStatus])

  const deployJob = useJob(
    projectId,
    'deploy',
    async (j) => {
      const res = (j.result || null) as DeployResult | null
      setResult(res)
      setSheetRows(normalizeSheets(res))
      setAutoRows(normalizeAutomations(res))
      setGroupRows(normalizeGroups(res))
      if (res?.error) setDeployError(String(res.error))
      const failed =
        normalizeSheets(res).filter((r) => r.err).length +
        normalizeAutomations(res).filter((r) => r.err).length +
        normalizeGroups(res).filter((r) => r.created === false).length
      if (failed) message.warning(`部署完成,但有 ${failed} 项失败`)
      else message.success('氚云应用生成完成')
      onDeployed?.()
    },
    (j) => message.error(`生成失败:${j.error || '未知错误'}`),
  )

  const verifyJob = useJob(
    projectId,
    'verify',
    async (j) => {
      setVerifyResult(j.result ?? null)
      message.success('回读核对完成')
    },
    (j) => message.error(`回读核对失败:${j.error || '未知错误'}`),
  )

  async function runDeploy(useForce: boolean) {
    setDeployError('')
    try {
      // 契约为请求体 force;同时带 query 以兼容尚未迁移的旧后端。
      const url = `/api/projects/${projectId}/deploy${useForce ? '?force=true' : ''}`
      await deployJob.start(() => post(url, useForce ? { force: true } : {}))
    } catch (e) {
      message.error(errMsg(e))
    }
  }

  function deploy() {
    if (force) {
      modal.confirm({
        title: '确认强制重存(force)?',
        content:
          '强制重存会整表覆盖线上表单,抹掉界面上的手工配置(列宽、显隐、必填等),且不可恢复。请确认后继续。',
        okText: '强制重存',
        okButtonProps: { danger: true },
        cancelText: '取消',
        onOk: () => runDeploy(true),
      })
      return
    }
    runDeploy(false)
  }

  async function verify() {
    try {
      await verifyJob.start(() => post(`/api/projects/${projectId}/verify`, {}))
    } catch (e) {
      message.error(errMsg(e))
    }
  }

  const configured = !!status?.configured
  const hasToken = status?.hasToken ?? project.hasToken
  const verifySheets: any[] = Array.isArray(verifyResult?.sheets) ? verifyResult.sheets : []
  const verifyAllOk = verifyResult?.all_ok
  const deployAllOk = result?.all_ok

  const deployColumns = [
    { title: '表 key', dataIndex: 'key' },
    {
      title: '结果',
      dataIndex: 'created',
      width: 120,
      render: (v: boolean, r: DeploySheetResult) =>
        r.err ? (
          <Tag color="red">失败</Tag>
        ) : v ? (
          <Tag color="green">已创建</Tag>
        ) : (
          <Tag color="blue">已存在</Tag>
        ),
    },
    { title: '表单编码', dataIndex: 'code', width: 200, render: (v: string) => v || '-' },
    { title: '详情', dataIndex: 'detail', render: (v: string) => v || '-' },
    {
      title: '错误',
      dataIndex: 'err',
      render: (v: string) =>
        v ? <Typography.Text type="danger">{v}</Typography.Text> : '-',
    },
  ]

  const autoColumns = [
    { title: '自动化 key', dataIndex: 'key' },
    {
      title: '结果',
      dataIndex: 'created',
      width: 120,
      render: (v: boolean, r: DeployAutomationResult) =>
        r.err ? <Tag color="red">失败</Tag> : v ? <Tag color="green">已创建</Tag> : <Tag color="blue">已更新</Tag>,
    },
    { title: 'ObjectId', dataIndex: 'objectId', width: 320, render: (v: string) => v || '-' },
    {
      title: '错误',
      dataIndex: 'err',
      render: (v: string) =>
        v ? <Typography.Text type="danger">{v}</Typography.Text> : '-',
    },
  ]

  return (
    <div>
      <Card
        title="凭据状态"
        style={{ marginBottom: 12 }}
        extra={
          <Button icon={<ReloadOutlined />} loading={statusLoading} onClick={loadStatus}>
            刷新
          </Button>
        }
      >
        <Descriptions column={4} size="small">
          <Descriptions.Item label="应用编码">
            {status?.appCode || project.appCode || '-'}
          </Descriptions.Item>
          <Descriptions.Item label="engineCode">{status?.engineCode || '-'}</Descriptions.Item>
          <Descriptions.Item label="h3_token">
            {hasToken ? <Tag color="green">已配置</Tag> : <Tag color="red">未配置</Tag>}
          </Descriptions.Item>
          <Descriptions.Item label="Token 有效性">
            {status?.tokenExpired ? (
              <Tag color="red">已过期</Tag>
            ) : status?.tokenValid ? (
              <Tag color="green">有效</Tag>
            ) : (
              <Tag color="orange">未知</Tag>
            )}
          </Descriptions.Item>
        </Descriptions>
        {status?.tokenExpired ? (
          <Alert
            type="error"
            showIcon
            style={{ marginTop: 8 }}
            message="h3_token 已过期"
            description="请在项目设置中更新 h3_token 后再生成应用。"
          />
        ) : null}
        {!configured ? (
          <Alert
            type="warning"
            showIcon
            style={{ marginTop: 8 }}
            message="缺少 h3_token 或应用编码"
            description="请在项目设置中补充 h3_token 与应用编码后再生成应用。"
          />
        ) : null}
      </Card>

      <Card
        title="生成氚云应用"
        extra={
          <Space>
            <Space size={4}>
              <Switch
                size="small"
                checked={force}
                disabled={!canWrite}
                onChange={setForce}
              />
              <Typography.Text type={force ? 'danger' : 'secondary'}>
                强制重存(force)
              </Typography.Text>
            </Space>
            <Button
              type="primary"
              icon={<CloudUploadOutlined />}
              loading={deployJob.running}
              disabled={!canWrite || !!gate || deployJob.running}
              onClick={deploy}
            >
              生成氚云应用
            </Button>
            <Button
              icon={<SafetyCertificateOutlined />}
              loading={verifyJob.running}
              disabled={!canWrite || verifyJob.running}
              onClick={verify}
            >
              回读核对
            </Button>
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
        {force ? (
          <Alert
            type="error"
            showIcon
            style={{ marginBottom: 12 }}
            message="已开启强制重存"
            description="部署时会整表覆盖线上表单,抹掉界面手工配置;点击「生成氚云应用」后将再次确认。"
          />
        ) : null}
        {deployError ? (
          <Alert type="error" showIcon message="部署返回错误" description={deployError} style={{ marginBottom: 12 }} />
        ) : null}

        {result ? (
          <Alert
            type={deployAllOk ? 'success' : 'error'}
            showIcon
            style={{ marginBottom: 12 }}
            message={deployAllOk ? '部署成功(ALL OK)' : '部署存在失败项'}
            description={`表单 ${sheetRows.filter((r) => !r.err).length}/${sheetRows.length} 成功;分组 ${
              groupRows.filter((r) => r.created !== false).length
            }/${groupRows.length} 成功;自动化 ${
              autoRows.filter((r) => !r.err).length
            }/${autoRows.length} 成功。`}
          />
        ) : null}

        {sheetRows.length ? (
          <>
            <Typography.Text strong>表单</Typography.Text>
            <Table<DeploySheetResult>
              size="small"
              rowKey={(r) => r.key}
              style={{ marginTop: 8 }}
              pagination={false}
              dataSource={sheetRows}
              columns={deployColumns as any}
            />
          </>
        ) : null}

        {groupRows.length ? (
          <>
            <Typography.Text strong style={{ display: 'block', marginTop: 12 }}>
              分组(应用菜单)
            </Typography.Text>
            <Table<DeployGroupResult>
              size="small"
              rowKey={(r) => r.group}
              style={{ marginTop: 8 }}
              pagination={false}
              dataSource={groupRows}
              columns={[
                { title: '分组名', dataIndex: 'group' },
                {
                  title: '结果',
                  dataIndex: 'created',
                  width: 100,
                  render: (v: boolean) => (v === false ? <Tag color="red">失败</Tag> : <Tag color="green">成功</Tag>),
                },
                { title: '分组码', dataIndex: 'code', render: (c: string) => <span className="mono">{c || '-'}</span> },
                { title: '说明', dataIndex: 'detail' },
              ]}
            />
          </>
        ) : null}

        {autoRows.length ? (
          <>
            <Typography.Text strong style={{ display: 'block', marginTop: 12 }}>
              自动化
            </Typography.Text>
            <Table<DeployAutomationResult>
              size="small"
              rowKey={(r) => r.key}
              style={{ marginTop: 8 }}
              pagination={false}
              dataSource={autoRows}
              columns={autoColumns as any}
            />
          </>
        ) : null}

        {!sheetRows.length && !autoRows.length && !groupRows.length ? (
          <Empty description="尚未生成应用" />
        ) : null}
      </Card>

      {verifyResult ? (
        <Card title="回读核对结果" style={{ marginTop: 16 }}>
          <Alert
            type={verifyAllOk ? 'success' : 'warning'}
            showIcon
            style={{ marginBottom: 12 }}
            message={verifyAllOk ? '回读核对通过(ALL OK)' : '回读核对存在差异'}
          />
          {verifySheets.length ? (
            <Table
              size="small"
              rowKey={(r: any) => r.key || r.code || JSON.stringify(r).slice(0, 24)}
              pagination={false}
              dataSource={verifySheets}
              columns={Object.keys(verifySheets[0] || {}).map((k) => ({
                title: k,
                dataIndex: k,
                render: (v: any) =>
                  typeof v === 'boolean' ? (v ? '是' : '否') : typeof v === 'object' ? JSON.stringify(v) : String(v ?? ''),
              }))}
            />
          ) : (
            <pre className="design-check-pre">{JSON.stringify(verifyResult, null, 2)}</pre>
          )}
        </Card>
      ) : null}
    </div>
  )
}
