import { useCallback, useEffect, useState } from 'react'
import {
  App as AntApp,
  Button,
  Card,
  Form,
  Input,
  Modal,
  Popconfirm,
  Select,
  Space,
  Switch,
  Table,
  Tag,
} from 'antd'
import { DeleteOutlined, EditOutlined, PlusOutlined, ReloadOutlined } from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import dayjs from 'dayjs'
import { del, errMsg, get, patch, post, User } from '../api/client'

const ROLE_OPTIONS = [
  { value: 'admin', label: '管理员' },
  { value: 'designer', label: '设计者' },
  { value: 'viewer', label: '只读' },
]

const ROLE_META: Record<string, { color: string; text: string }> = {
  admin: { color: 'red', text: '管理员' },
  designer: { color: 'blue', text: '设计者' },
  viewer: { color: 'default', text: '只读' },
}

export default function Users({ me }: { me: User }) {
  const { message } = AntApp.useApp()
  const [rows, setRows] = useState<User[]>([])
  const [loading, setLoading] = useState(true)
  const [open, setOpen] = useState(false)
  const [editing, setEditing] = useState<User | null>(null)
  const [saving, setSaving] = useState(false)
  const [form] = Form.useForm()

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const data = await get<User[]>('/api/users')
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

  function openCreate() {
    setEditing(null)
    form.resetFields()
    form.setFieldsValue({ role: 'designer', active: true })
    setOpen(true)
  }

  function openEdit(u: User) {
    setEditing(u)
    form.setFieldsValue({
      displayName: u.displayName,
      role: u.role,
      active: u.active,
      password: '',
    })
    setOpen(true)
  }

  async function submit() {
    let v: any
    try {
      v = await form.validateFields()
    } catch {
      return
    }
    setSaving(true)
    try {
      if (editing) {
        const payload: any = {
          displayName: v.displayName,
          role: v.role,
          active: v.active,
        }
        if (v.password) payload.password = v.password
        await patch(`/api/users/${editing.id}`, payload)
        message.success('用户已更新')
      } else {
        await post('/api/users', {
          email: v.email,
          password: v.password,
          displayName: v.displayName || v.email,
          role: v.role,
        })
        message.success('用户已创建')
      }
      setOpen(false)
      load()
    } catch (e) {
      message.error(errMsg(e))
    } finally {
      setSaving(false)
    }
  }

  async function removeUser(u: User) {
    try {
      await del(`/api/users/${u.id}`)
      message.success('用户已删除')
      load()
    } catch (e) {
      message.error(errMsg(e))
    }
  }

  const columns: ColumnsType<User> = [
    { title: '邮箱', dataIndex: 'email', key: 'email' },
    {
      title: '显示名称',
      dataIndex: 'displayName',
      key: 'displayName',
      render: (v: string) => v || '-',
    },
    {
      title: '角色',
      dataIndex: 'role',
      key: 'role',
      width: 120,
      render: (r: string) => {
        const meta = ROLE_META[r] || { color: 'default', text: r }
        return <Tag color={meta.color}>{meta.text}</Tag>
      },
    },
    {
      title: '状态',
      dataIndex: 'active',
      key: 'active',
      width: 100,
      render: (v: boolean) => (v ? <Tag color="green">启用</Tag> : <Tag color="default">停用</Tag>),
    },
    {
      title: '创建时间',
      dataIndex: 'createdAt',
      key: 'createdAt',
      width: 170,
      render: (v: string) => (v ? dayjs(v).format('YYYY-MM-DD HH:mm') : '-'),
    },
    {
      title: '操作',
      key: 'actions',
      width: 170,
      render: (_, u) => (
        <Space>
          <Button size="small" type="link" icon={<EditOutlined />} onClick={() => openEdit(u)}>
            编辑
          </Button>
          {u.id !== me.id ? (
            <Popconfirm
              title="确认删除该用户?"
              okText="删除"
              okButtonProps={{ danger: true }}
              cancelText="取消"
              onConfirm={() => removeUser(u)}
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
      title="用户管理"
      extra={
        <Space>
          <Button icon={<ReloadOutlined />} onClick={load}>
            刷新
          </Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
            新建用户
          </Button>
        </Space>
      }
    >
      <Table<User>
        rowKey="id"
        columns={columns}
        dataSource={rows}
        loading={loading}
        pagination={{ pageSize: 10, showSizeChanger: false }}
      />

      <Modal
        title={editing ? '编辑用户' : '新建用户'}
        open={open}
        onOk={submit}
        confirmLoading={saving}
        onCancel={() => setOpen(false)}
        okText={editing ? '保存' : '创建'}
        cancelText="取消"
        destroyOnClose
      >
        <Form form={form} layout="vertical" preserve={false}>
          {!editing ? (
            <>
              <Form.Item
                name="email"
                label="邮箱"
                rules={[
                  { required: true, message: '请输入邮箱' },
                  { type: 'email', message: '邮箱格式不正确' },
                ]}
              >
                <Input placeholder="user@example.com" />
              </Form.Item>
              <Form.Item
                name="password"
                label="密码"
                rules={[
                  { required: true, message: '请输入密码' },
                  { min: 6, message: '密码至少 6 位' },
                ]}
              >
                <Input.Password placeholder="至少 6 位" />
              </Form.Item>
            </>
          ) : (
            <Form.Item name="password" label="重置密码" extra="留空表示不修改">
              <Input.Password placeholder="留空不修改" />
            </Form.Item>
          )}
          <Form.Item name="displayName" label="显示名称">
            <Input placeholder="用户名称" />
          </Form.Item>
          <Form.Item name="role" label="角色" rules={[{ required: true, message: '请选择角色' }]}>
            <Select options={ROLE_OPTIONS} />
          </Form.Item>
          {editing ? (
            <Form.Item name="active" label="启用" valuePropName="checked">
              <Switch />
            </Form.Item>
          ) : null}
        </Form>
      </Modal>
    </Card>
  )
}
