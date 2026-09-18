import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  App as AntApp,
  Button,
  Card,
  Form,
  Input,
  Modal,
  Popconfirm,
  Space,
  Table,
  Tag,
  Typography,
} from 'antd'
import {
  DeleteOutlined,
  PlusOutlined,
  ReloadOutlined,
  RightOutlined,
  SettingOutlined,
} from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import dayjs from 'dayjs'
import { del, errMsg, get, post, Project, STATUS_META, User } from '../api/client'
import ProjectSettingsModal from '../components/ProjectSettingsModal'

export default function Projects({ me }: { me: User }) {
  const nav = useNavigate()
  const { message } = AntApp.useApp()
  const [rows, setRows] = useState<Project[]>([])
  const [loading, setLoading] = useState(true)
  const [open, setOpen] = useState(false)
  const [saving, setSaving] = useState(false)
  const [settingsFor, setSettingsFor] = useState<Project | null>(null)
  const [form] = Form.useForm()

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const data = await get<Project[]>('/api/projects')
      setRows(Array.isArray(data) ? data : [])
    } catch (e) {
      message.error(errMsg(e))
      setRows([])
    } finally {
      setLoading(false)
    }
  }, [message])

  useEffect(() => {
    load()
  }, [load])

  async function createProject() {
    let v: any
    try {
      v = await form.validateFields()
    } catch {
      return
    }
    setSaving(true)
    try {
      const p = await post<Project>('/api/projects', {
        name: v.name,
        title: v.title,
        engineCode: (v.engineCode || '').trim(),
        appCode: v.appCode || '',
        h3Token: v.h3Token || '',
      })
      message.success('项目创建成功')
      setOpen(false)
      form.resetFields()
      if (p?.id) {
        nav(`/projects/${p.id}`)
      } else {
        load()
      }
    } catch (e) {
      message.error(errMsg(e))
    } finally {
      setSaving(false)
    }
  }

  async function removeProject(p: Project) {
    try {
      await del(`/api/projects/${p.id}`)
      message.success('项目已删除')
      load()
    } catch (e) {
      message.error(errMsg(e))
    }
  }

  const canDelete = (p: Project) => me.role === 'admin' || p.ownerId === me.id

  const columns: ColumnsType<Project> = [
    {
      title: '项目名称',
      dataIndex: 'title',
      key: 'title',
      render: (text: string, p) => (
        <a onClick={() => nav(`/projects/${p.id}`)}>
          <RightOutlined style={{ fontSize: 10, marginRight: 6 }} />
          {text || p.slug}
        </a>
      ),
    },
    {
      title: '项目标识',
      dataIndex: 'slug',
      key: 'slug',
      width: 180,
      render: (v: string) => <Typography.Text code>{v}</Typography.Text>,
    },
    {
      title: '应用编码',
      dataIndex: 'appCode',
      key: 'appCode',
      width: 180,
      render: (v: string) => v || <Typography.Text type="secondary">-</Typography.Text>,
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 120,
      render: (s: string) => {
        const meta = STATUS_META[s] || { color: 'default', text: s || '未知' }
        return <Tag color={meta.color}>{meta.text}</Tag>
      },
    },
    {
      title: '更新时间',
      dataIndex: 'updatedAt',
      key: 'updatedAt',
      width: 180,
      render: (v: string) => (v ? dayjs(v).format('YYYY-MM-DD HH:mm') : '-'),
    },
    {
      title: '操作',
      key: 'actions',
      width: 230,
      render: (_, p) => (
        <Space>
          <Button size="small" type="link" onClick={() => nav(`/projects/${p.id}`)}>
            打开
          </Button>
          <Button
            size="small"
            type="link"
            icon={<SettingOutlined />}
            disabled={!canDelete(p)}
            onClick={() => setSettingsFor(p)}
          >
            设置
          </Button>
          {canDelete(p) ? (
            <Popconfirm
              title="确认删除该项目?"
              description="项目工作区文件与数据将一并删除,且不可恢复。"
              okText="删除"
              okButtonProps={{ danger: true }}
              cancelText="取消"
              onConfirm={() => removeProject(p)}
            >
              <Button size="small" type="link" danger icon={<DeleteOutlined />}>
                删除
              </Button>
            </Popconfirm>
          ) : null}
        </Space>
      ),
    },
  ]

  return (
    <Card
      title="项目列表"
      extra={
        <Space>
          <Button icon={<ReloadOutlined />} onClick={load}>
            刷新
          </Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setOpen(true)}>
            新建项目
          </Button>
        </Space>
      }
    >
      <Table<Project>
        rowKey="id"
        columns={columns}
        dataSource={rows}
        loading={loading}
        pagination={{ pageSize: 10, showSizeChanger: false }}
        locale={{ emptyText: '暂无项目,点击右上角「新建项目」开始' }}
      />

      <Modal
        title="新建项目"
        open={open}
        onOk={createProject}
        confirmLoading={saving}
        onCancel={() => setOpen(false)}
        okText="创建"
        cancelText="取消"
        width={620}
        destroyOnClose
      >
        <Form form={form} layout="vertical" preserve={false}>
          <Form.Item
            name="title"
            label="项目名称"
            rules={[{ required: true, message: '请输入项目名称' }]}
          >
            <Input placeholder="例如:连锁门店管理系统" maxLength={120} />
          </Form.Item>
          <Form.Item
            name="name"
            label="项目标识(slug)"
            tooltip="同时作为项目目录名,仅字母数字下划线,字母开头"
            rules={[
              { required: true, message: '请输入项目标识' },
              {
                pattern: /^[A-Za-z][A-Za-z0-9_]*$/,
                message: '字母开头,只能包含字母、数字、下划线',
              },
            ]}
          >
            <Input placeholder="例如:store_system" maxLength={48} />
          </Form.Item>
          <Form.Item
            name="engineCode"
            label="引擎编码(engineCode)"
            tooltip="氚云引擎编码,新增项目时填写;粘贴下方 h3_token 可自动带出(仍可修改)"
            rules={[{ required: true, message: '请输入引擎编码' }]}
          >
            <Input placeholder="例如:fs1tkeu2ap4kb4hp" maxLength={64} />
          </Form.Item>
          <Form.Item
            name="appCode"
            label="应用编码(appCode)"
            tooltip="先在氚云后台创建应用,再复制其应用编码填入;本系统不自动创建应用。可先留空,生成应用前补填"
          >
            <Input placeholder="例如:App_store" maxLength={64} />
          </Form.Item>
          <Form.Item
            name="h3Token"
            label="h3_token"
            tooltip="氚云登录后的 JWT,长字符串;粘贴后自动解析引擎编码并填入上方;加密存储且绝不回显"
          >
            <Input.TextArea rows={4} placeholder="粘贴氚云 h3_token(JWT)"
              onChange={(e) => {
                const tok = (e.target.value || '').trim().replace(/^Bearer\s+/i, '')
                const parts = tok.split('.')
                if (parts.length === 3) {
                  try {
                    const p = JSON.parse(decodeURIComponent(escape(atob(
                      parts[1].replace(/-/g, '+').replace(/_/g, '/')))))
                    if (p.enginecode) form.setFieldValue('engineCode', p.enginecode)
                  } catch { /* 非法 token 忽略 */ }
                }
              }} />
          </Form.Item>
        </Form>
      </Modal>

      <ProjectSettingsModal
        open={!!settingsFor}
        project={settingsFor}
        onClose={() => setSettingsFor(null)}
        onSaved={load}
      />
    </Card>
  )
}
