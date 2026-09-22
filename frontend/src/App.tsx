import { useEffect, useState } from 'react'
import { Navigate, Route, Routes, useNavigate, useLocation } from 'react-router-dom'
import { Layout, Menu, Dropdown, Avatar, Spin, Form, Input, Modal, Upload, Button, App as AntApp } from 'antd'
import {
  UserOutlined,
  ProjectOutlined,
  SettingOutlined,
  TeamOutlined,
  DatabaseOutlined,
  LogoutOutlined,
  KeyOutlined,
  ThunderboltFilled,
  UploadOutlined,
  MenuFoldOutlined,
  MenuUnfoldOutlined,
} from '@ant-design/icons'
import { errMsg, get, post, patch, avatarUrl, setUnauthorizedHandler, User } from './api/client'
import Login from './pages/Login'
import Projects from './pages/Projects'
import ProjectWorkbench from './pages/ProjectWorkbench'
import Library from './pages/Library'
import Settings from './pages/Settings'
import Users from './pages/Users'
import ThemeToggle from './components/ThemeToggle'
import { useTheme } from './theme/ThemeContext'

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
  const { dark } = useTheme()
  const menuTheme = dark ? 'dark' : 'light'
  const [pwdOpen, setPwdOpen] = useState(false)
  const [pwdLoading, setPwdLoading] = useState(false)
  const [profileOpen, setProfileOpen] = useState(false)
  const [profileLoading, setProfileLoading] = useState(false)
  const [profileForm] = Form.useForm()
  const [form] = Form.useForm()
  // 左侧导航:用户可主动显示/隐藏,偏好持久化到 localStorage。
  // 注意:偏好(siderPref)与「窄屏自动折叠」是两回事——窄屏强制折叠,宽屏恢复用户偏好,
  // 只有用户主动点击才写入偏好(否则窗口一缩小就被永久记住)。
  const [siderPref, setSiderPref] = useState(() => {
    try {
      return localStorage.getItem('h3ac.siderCollapsed') === '1'
    } catch {
      return false // 隐私模式等 localStorage 不可用
    }
  })
  const [siderCollapsed, setSiderCollapsed] = useState(siderPref)
  const [narrow, setNarrow] = useState(false)
  useEffect(() => {
    const mq = window.matchMedia('(max-width: 991.98px)')
    const apply = () => {
      setNarrow(mq.matches)
      setSiderCollapsed(mq.matches ? true : siderPref)
    }
    apply()
    mq.addEventListener('change', apply)
    return () => mq.removeEventListener('change', apply)
  }, [siderPref])
  const toggleSider = () => {
    if (narrow) return // 窄屏保持折叠,点展开按钮无效(避免与响应式打架)
    setSiderPref((v) => {
      const next = !v
      try {
        localStorage.setItem('h3ac.siderCollapsed', next ? '1' : '0')
      } catch {
        /* 忽略:隐私模式下 localStorage 可能不可用 */
      }
      setSiderCollapsed(next)
      return next
    })
  }

  const isAdmin = me.role === 'admin'

  const selectedKey = loc.pathname.startsWith('/projects')
    ? 'projects'
    : loc.pathname.startsWith('/library')
      ? 'library'
      : loc.pathname.startsWith('/users')
        ? 'users'
        : loc.pathname.startsWith('/settings')
          ? 'settings'
          : 'projects'

  const menuItems = [
    { key: 'projects', icon: <ProjectOutlined />, label: '项目' },
    { key: 'library', icon: <DatabaseOutlined />, label: '资料库' },
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

  async function openProfile() {
    profileForm.setFieldsValue({ displayName: me.displayName || '' })
    setProfileOpen(true)
  }

  async function submitProfile() {
    let v: any
    try {
      v = await profileForm.validateFields()
    } catch {
      return
    }
    setProfileLoading(true)
    try {
      const u = await patch<User>('/api/auth/profile', { displayName: v.displayName })
      setMe(u)
      message.success('资料已更新')
      setProfileOpen(false)
    } catch (e) {
      message.error(errMsg(e))
    } finally {
      setProfileLoading(false)
    }
  }

  const userMenu = {
    items: [
      { key: 'profile', icon: <UserOutlined />, label: '个人资料' },
      { key: 'pwd', icon: <KeyOutlined />, label: '修改密码' },
      { type: 'divider' as const },
      { key: 'logout', icon: <LogoutOutlined />, label: '退出登录' },
    ],
    onClick: ({ key }: { key: string }) => {
      if (key === 'profile') openProfile()
      if (key === 'pwd') setPwdOpen(true)
      if (key === 'logout') logout()
    },
  }

  const pageTitle =
    selectedKey === 'projects'
      ? '项目工作台'
      : selectedKey === 'library'
        ? '资料库'
        : selectedKey === 'users'
          ? '用户管理'
          : '系统设置'

  return (
    <Layout className="app-shell">
      <Layout.Sider
        className="app-sider"
        theme={menuTheme}
        width={210}
        collapsedWidth={64}
        collapsed={siderCollapsed}
        trigger={null}
      >
        <div className="app-brand">
          <span className="app-brand-mark">
            <ThunderboltFilled />
          </span>
          <span className="app-brand-text">氚云应用生成平台</span>
          <button
            type="button"
            className="app-sider-toggle"
            onClick={toggleSider}
            title="隐藏侧边栏"
            aria-label="隐藏侧边栏"
          >
            <MenuFoldOutlined />
          </button>
        </div>
        <Menu
          className="app-sider-menu"
          theme={menuTheme}
          mode="inline"
          inlineCollapsed={siderCollapsed}
          selectedKeys={[selectedKey]}
          items={menuItems}
          onClick={({ key }) => nav('/' + key)}
        />
        <div className="app-sider-foot">需求 → 设计 → 生成</div>
      </Layout.Sider>

      <Layout className="app-main">
        <Layout.Header className="app-header">
          <div className="app-header-left">
            {siderCollapsed && !narrow ? (
              <button
                type="button"
                className="app-header-toggle"
                onClick={toggleSider}
                title="显示侧边栏"
                aria-label="显示侧边栏"
              >
                <MenuUnfoldOutlined />
              </button>
            ) : null}
            <div className="app-header-title">{pageTitle}</div>
          </div>
          <div className="app-header-right">
            <ThemeToggle />
            <Dropdown menu={userMenu} placement="bottomRight">
              <div className="header-user">
                <Avatar
                  size="small"
                  src={avatarUrl(me) || undefined}
                  icon={<UserOutlined />}
                  style={{ marginRight: 8 }}
                />
                <span>{me.displayName || me.email}</span>
                {isAdmin ? <span className="header-user-role">管理员</span> : null}
              </div>
            </Dropdown>
          </div>
        </Layout.Header>

        <Layout.Content className="content-area">
          <Routes>
            <Route path="/" element={<Navigate to="/projects" replace />} />
            <Route path="/login" element={<Navigate to="/projects" replace />} />
            <Route path="/projects" element={<Projects me={me} />} />
            <Route path="/projects/:id" element={<ProjectWorkbench me={me} />} />
            <Route path="/library" element={<Library me={me} />} />
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
        title="个人资料"
        open={profileOpen}
        onOk={submitProfile}
        confirmLoading={profileLoading}
        onCancel={() => setProfileOpen(false)}
        okText="保存"
        cancelText="取消"
        destroyOnClose
      >
        <Form form={profileForm} layout="vertical" preserve={false}>
          <Form.Item label="头像">
            <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
              <Avatar size={72} src={avatarUrl(me) || undefined} icon={<UserOutlined />} />
              <Upload
                showUploadList={false}
                accept="image/png,image/jpeg,image/gif,image/webp,image/bmp"
                customRequest={async (opt) => {
                  try {
                    const fd = new FormData()
                    fd.append('file', opt.file as File)
                    const u = await post<User>('/api/auth/avatar', fd)
                    setMe(u)
                    message.success('头像已更新')
                    opt.onSuccess?.(u)
                  } catch (e) {
                    message.error(errMsg(e))
                    opt.onError?.(e as any)
                  }
                }}
              >
                <Button icon={<UploadOutlined />}>上传头像</Button>
              </Upload>
            </div>
          </Form.Item>
          <Form.Item
            name="displayName"
            label="显示名称"
            rules={[{ required: true, message: '请输入显示名称' }]}
          >
            <Input placeholder="展示给其他成员的名称" />
          </Form.Item>
        </Form>
      </Modal>

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
