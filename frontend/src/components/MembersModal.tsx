import { useEffect, useState } from 'react'
import { App as AntApp, Button, Modal, Popconfirm, Select, Space, Table, Tag, Typography } from 'antd'
import { del, errMsg, get, post, Project, ProjectMember, User } from '../api/client'

/** 项目成员授权(owner/admin 使用):把项目以 viewer/designer 角色授权给他人。 */
export default function MembersModal({
  open,
  project,
  me,
  onClose,
}: {
  open: boolean
  project: Project
  me: User
  onClose: () => void
}) {
  const { message } = AntApp.useApp()
  const [members, setMembers] = useState<ProjectMember[]>([])
  const [users, setUsers] = useState<User[]>([])
  const [userId, setUserId] = useState<number | undefined>()
  const [role, setRole] = useState<string>('viewer')
  const [loading, setLoading] = useState(false)

  // 共享管理仅限项目所有者或管理员(被共享者不能再转授)
  const canManage = me.role === 'admin' || project.ownerId === me.id

  async function load() {
    setLoading(true)
    try {
      setMembers(await get<ProjectMember[]>(`/api/projects/${project.id}/members`))
      setUsers(await get<User[]>('/api/users/directory'))
    } catch (e) {
      message.error(errMsg(e))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (open) load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, project.id])

  async function add() {
    if (!userId) {
      message.warning('请选择用户')
      return
    }
    try {
      setMembers(
        await post<ProjectMember[]>(`/api/projects/${project.id}/members`, { userId, role }),
      )
      setUserId(undefined)
      message.success('已授权')
    } catch (e) {
      message.error(errMsg(e))
    }
  }

  async function remove(uid: number) {
    try {
      await del(`/api/projects/${project.id}/members/${uid}`)
      message.success('已移除')
      load()
    } catch (e) {
      message.error(errMsg(e))
    }
  }

  const candidates = users.filter((u) => !members.some((m) => m.userId === u.id))

  return (
    <Modal title={`成员授权 · ${project.title}`} open={open} onCancel={onClose} footer={null} width={640}>
      {canManage ? (
        <Space style={{ marginBottom: 12 }}>
          <Select
            style={{ width: 240 }}
            showSearch
            optionFilterProp="label"
            placeholder="选择用户"
            value={userId}
            onChange={setUserId}
            options={candidates.map((u) => ({
              value: u.id,
              label: `${u.displayName || u.email}(${u.email})`,
            }))}
          />
          <Select
            style={{ width: 120 }}
            value={role}
            onChange={setRole}
            options={[
              { value: 'viewer', label: '只读' },
              { value: 'designer', label: '可编辑' },
            ]}
          />
          <Button type="primary" onClick={add}>
            授权
          </Button>
        </Space>
      ) : (
        <Typography.Text type="secondary" style={{ display: 'block', marginBottom: 12 }}>
          仅项目所有者或管理员可管理共享成员;被共享的项目不能再转授他人。
        </Typography.Text>
      )}
      <Table
        rowKey="userId"
        size="small"
        loading={loading}
        dataSource={members}
        pagination={false}
        columns={[
          {
            title: '用户',
            render: (_, m) => `${m.displayName || ''}${m.email ? `(${m.email})` : `#${m.userId}`}`,
          },
          {
            title: '项目角色',
            dataIndex: 'role',
            width: 120,
            render: (r: string) => (
              <Tag color={r === 'designer' ? 'blue' : 'default'}>
                {r === 'designer' ? '可编辑' : '只读'}
              </Tag>
            ),
          },
          {
            title: '',
            width: 80,
            render: (_, m) =>
              canManage ? (
                <Popconfirm title="移除该成员?" onConfirm={() => remove(m.userId)}>
                  <a>移除</a>
                </Popconfirm>
              ) : null,
          },
        ]}
      />
    </Modal>
  )
}
