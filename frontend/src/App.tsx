import { useEffect, useState } from 'react'
import { Navigate, Route, Routes, useNavigate, useLocation } from 'react-router-dom'
import { Layout, Menu, Dropdown, Avatar, Spin, Form, Input, Modal, App as AntApp } from 'antd'
import {
  UserOutlined,
  ProjectOutlined,
  SettingOutlined,
  TeamOutlined,
  LogoutOutlined,
  KeyOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons'
import { errMsg, get, post, setUnauthorizedHandler, User } from './api/client'
import Login from './pages/Login'
import Projects from './pages/Projects'
import ProjectWorkbench from './pages/ProjectWorkbench'
import Settings from './pages/Settings'
import Users from './pages/Users'

export default function App() {
  const [me, setMe] = useState<User | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    setUnauthorizedHandler(() => setMe(null))
    get<User>('/api/auth/me')
      .then((u) => setMe(u))
      .catch(() => setMe(null))
      .finally(() => setLoading(false))
    return () => setUnauthorizedHandler(null)
  }, [])

  if (loading) {
    return (
      <div className="center-screen">
        <Spin size="large" tip="加载中..." />
      </div>
    )
  }

  if (!me) {
    return (
      <Routes>
        <Route path="/login" element={<Login onLoggedIn={setMe} />} />
        <Route path="*" element={<Navigate to="/login" replace />} />
      </Routes>
    )
  }

  return <MainLayout me={me} setMe={setMe} />
}

function MainLayout({ me, setMe }: { me: User; setMe: (u: User | null) => void }) {
  const nav = useNavigate()
  const loc = useLocation()
  const { message } = AntApp.useApp()
  const [pwdOpen, setPwdOpen] = useState(false)
  const [pwdLoading, setPwdLoading] = useState(false)
  const [form] = Form.useForm()

  const isAdmin = me.role === 'admin'

  const selectedKey = loc.pathname.startsWith('/projects')
    ? 'projects'
    : loc.pathname.startsWith('/users')
      ? 'users'
      : loc.pathname.startsWith('/settings')
        ? 'settings'
        : 'projects'

  const menuItems = [
    { key: 'projects', icon: <ProjectOutlined />, label: '项目' },
    ...(isAdmin
      ? [
          { key: 'settings', icon: <SettingOutlined />, label: '系统设置' },
          { key: 'users', icon: <TeamOutlined />, label: '用户管理' },
        ]
      : []),
  ]

  async function logout() {
    try {
      await post('/api/auth/logout')
    } catch {
      /* 忽略:会话可能已过期 */
    }
    setMe(null)
    nav('/login')
  }

  async function submitPassword() {
    let v: any
    try {
      v = await form.validateFields()
    } catch {
      return
    }
    setPwdLoading(true)
    try {
      await post('/api/auth/password', {
        oldPassword: v.oldPassword,
        newPassword: v.newPassword,
      })
      message.success('密码已修改')
      setPwdOpen(false)
      form.resetFields()
    } catch (e) {
      message.error(errMsg(e))
    } finally {
      setPwdLoading(false)
    }
  }

  const userMenu = {
    items: [
      { key: 'pwd', icon: <KeyOutlined />, label: '修改密码' },
      { type: 'divider' as const },
      { key: 'logout', icon: <LogoutOutlined />, label: '退出登录' },
    ],
    onClick: ({ key }: { key: string }) => {
      if (key === 'pwd') setPwdOpen(true)
      if (key === 'logout') logout()
    },
  }

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Layout.Sider theme="dark" width={210} breakpoint="lg" collapsedWidth={64}>
        <div style={{ height: 56, display: 'flex', alignItems: 'center', padding: '0 16px' }}>
          <ThunderboltOutlined style={{ color: '#1677ff', fontSize: 20, marginRight: 8 }} />
          <span className="app-logo">h3factory</span>
        </div>
        <Menu
          theme="dark"
          mode="inline"
          selectedKeys={[selectedKey]}
          items={menuItems}
          onClick={({ key }) => nav('/' + key)}
        />
      </Layout.Sider>
      <Layout>
        <Layout.Header className="app-header">
          <div style={{ color: '#fff', fontSize: 16, fontWeight: 500 }}>
            {selectedKey === 'projects' ? '项目工作台' : selectedKey === 'users' ? '用户管理' : '系统设置'}
          </div>
          <Dropdown menu={userMenu} placement="bottomRight">
            <div className="header-user">
              <Avatar size="small" icon={<UserOutlined />} style={{ marginRight: 8 }} />
              <span>{me.displayName || me.email}</span>
              {isAdmin ? <span style={{ marginLeft: 6, opacity: 0.6 }}>(管理员)</span> : null}
            </div>
          </Dropdown>
        </Layout.Header>
        <Layout.Content style={{ padding: 20 }}>
          <Routes>
            <Route path="/" element={<Navigate to="/projects" replace />} />
            <Route path="/login" element={<Navigate to="/projects" replace />} />
            <Route path="/projects" element={<Projects me={me} />} />
            <Route path="/projects/:id" element={<ProjectWorkbench me={me} />} />
            <Route
              path="/settings"
              element={isAdmin ? <Settings /> : <Navigate to="/projects" replace />}
            />
            <Route
              path="/users"
              element={isAdmin ? <Users me={me} /> : <Navigate to="/projects" replace />}
            />
            <Route path="*" element={<Navigate to="/projects" replace />} />
          </Routes>
        </Layout.Content>
      </Layout>

      <Modal
        title="修改密码"
        open={pwdOpen}
        onOk={submitPassword}
        confirmLoading={pwdLoading}
        onCancel={() => setPwdOpen(false)}
        okText="保存"
        cancelText="取消"
        destroyOnClose
      >
        <Form form={form} layout="vertical" preserve={false}>
          <Form.Item
            name="oldPassword"
            label="原密码"
            rules={[{ required: true, message: '请输入原密码' }]}
          >
            <Input.Password autoComplete="current-password" />
          </Form.Item>
          <Form.Item
            name="newPassword"
            label="新密码"
            rules={[
              { required: true, message: '请输入新密码' },
              { min: 6, message: '密码至少 6 位' },
            ]}
          >
            <Input.Password autoComplete="new-password" />
          </Form.Item>
          <Form.Item
            name="confirm"
            label="确认新密码"
            dependencies={['newPassword']}
            rules={[
              { required: true, message: '请再次输入新密码' },
              ({ getFieldValue }) => ({
                validator(_, value) {
                  if (!value || getFieldValue('newPassword') === value) return Promise.resolve()
                  return Promise.reject(new Error('两次输入的密码不一致'))
                },
              }),
            ]}
          >
            <Input.Password autoComplete="new-password" />
          </Form.Item>
        </Form>
      </Modal>
    </Layout>
  )
}
