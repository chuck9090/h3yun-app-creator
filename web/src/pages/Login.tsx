import { useEffect, useState } from 'react'
import { Alert, App as AntApp, Button, Form, Input, Spin } from 'antd'
import { LockOutlined, MailOutlined, SafetyOutlined, ThunderboltFilled } from '@ant-design/icons'
import { errMsg, get, HealthInfo, post, User } from '../api/client'
import ThemeToggle from '../components/ThemeToggle'

const FLOW_NODES = ['需求', '系统设计方案', '业务流程图', 'ER 表图谱', '生成应用']

export default function Login({ onLoggedIn }: { onLoggedIn: (u: User) => void }) {
  const { message } = AntApp.useApp()
  const [checking, setChecking] = useState(true)
  const [needsBootstrap, setNeedsBootstrap] = useState(false)
  const [backendDown, setBackendDown] = useState(false)
  const [loading, setLoading] = useState(false)
  const [mode, setMode] = useState<'login' | 'setPassword'>('login')
  const [pendingEmail, setPendingEmail] = useState('')
  const [loginForm] = Form.useForm()
  const [bootForm] = Form.useForm()
  const [setForm] = Form.useForm()

  useEffect(() => {
    get<HealthInfo>('/api/health')
      .then((h) => {
        setNeedsBootstrap(!!h?.needsBootstrap)
        setBackendDown(false)
      })
      .catch(() => setBackendDown(true))
      .finally(() => setChecking(false))
  }, [])

  async function finishLogin(email: string, password: string): Promise<boolean> {
    const r = await post<{ needPassword?: boolean }>('/api/auth/login', { email, password })
    if (r?.needPassword) return false
    const me = await get<User>('/api/auth/me')
    message.success('登录成功')
    onLoggedIn(me)
    return true
  }

  async function doLogin(values: any) {
    setLoading(true)
    try {
      const logged = await finishLogin(values.email, values.password)
      if (!logged) {
        setPendingEmail(values.email)
        setMode('setPassword')
        message.info('该账号尚未设置密码,请先设置密码')
      }
    } catch (e) {
      message.error(errMsg(e))
    } finally {
      setLoading(false)
    }
  }

  async function doBootstrap(values: any) {
    setLoading(true)
    try {
      await post('/api/auth/bootstrap', {
        email: values.email,
        password: values.password,
      })
      await finishLogin(values.email, values.password)
    } catch (e) {
      message.error(errMsg(e))
    } finally {
      setLoading(false)
    }
  }

  async function doSetPassword(values: any) {
    setLoading(true)
    try {
      await post('/api/auth/set-initial-password', {
        email: pendingEmail,
        code: values.code,
        password: values.password,
      })
      const me = await get<User>('/api/auth/me')
      message.success('密码已设置,登录成功')
      onLoggedIn(me)
    } catch (e) {
      message.error(errMsg(e))
    } finally {
      setLoading(false)
    }
  }

  const heading = needsBootstrap ? '初始化管理员' : mode === 'setPassword' ? '设置密码' : '登录'
  const subheading = needsBootstrap
    ? '创建第一个管理员账号后即可开始使用'
    : mode === 'setPassword'
      ? '该账号为首次登录,请先设置密码'
      : '使用邮箱与密码进入工作台'

  return (
    <div className="login-page">
      <div className="login-theme-switch">
        <ThemeToggle />
      </div>
      <div className="login-shell">
        <aside className="login-hero">
          <div className="login-hero-top">
            <span className="app-brand-mark" style={{ width: 38, height: 38, fontSize: 20 }}>
              <ThunderboltFilled />
            </span>
            <span style={{ fontWeight: 600, fontSize: 16, color: 'var(--text-1)' }}>
              氚云应用生成平台
            </span>
          </div>

          <h2 className="login-hero-title">从需求文档到可运行的氚云应用</h2>
          <p className="login-hero-sub">
            把「需求 → 系统设计方案 → 业务流程图 → ER 表图谱 → 生成应用」固化成一条流水线。
            建表、核对、ER、载荷全部脚本化,AI 只负责需求到设计这一段。
          </p>

          <div className="login-hero-flow">
            {FLOW_NODES.map((n, i) => (
              <span key={n} style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
                <span className={`login-hero-node${i === 0 ? ' is-brand' : ''}`}>{n}</span>
                {i < FLOW_NODES.length - 1 ? <span className="login-hero-sep">›</span> : null}
              </span>
            ))}
          </div>

          <div className="login-hero-foot">确定性部分脚本化 · 零 LLM 依赖</div>
        </aside>

        <section className="login-panel">
          <div className="login-panel-head">
            <h3>{heading}</h3>
            <p>{subheading}</p>
          </div>

          {backendDown ? (
            <Alert
              type="warning"
              showIcon
              style={{ marginBottom: 12 }}
              message="无法连接后端服务"
              description="请确认后端服务已启动后重试(开发模式下请用 start.ps1 同时启动前后端)。"
            />
          ) : null}

          {checking ? (
            <div style={{ textAlign: 'center', padding: 12 }}>
              <Spin />
            </div>
          ) : needsBootstrap ? (
            <>
              <Alert
                type="info"
                showIcon
                style={{ marginBottom: 12 }}
                message="系统尚未初始化"
                description="检测到系统中还没有用户,请先创建第一个管理员账号。"
              />
              <Form form={bootForm} layout="vertical" onFinish={doBootstrap} disabled={loading}>
                <Form.Item
                  name="email"
                  label="管理员邮箱"
                  rules={[
                    { required: true, message: '请输入邮箱' },
                    { type: 'email', message: '邮箱格式不正确' },
                  ]}
                >
                  <Input prefix={<MailOutlined />} placeholder="admin@local" autoComplete="username" />
                </Form.Item>
                <Form.Item
                  name="password"
                  label="密码"
                  rules={[
                    { required: true, message: '请输入密码' },
                    { min: 6, message: '密码至少 6 位' },
                  ]}
                >
                  <Input.Password prefix={<LockOutlined />} placeholder="至少 6 位" autoComplete="new-password" />
                </Form.Item>
                <Button type="primary" htmlType="submit" block loading={loading}>
                  初始化管理员
                </Button>
              </Form>
            </>
          ) : mode === 'setPassword' ? (
            <>
            <Alert
              type="info"
              showIcon
              style={{ marginBottom: 12 }}
              message="首次登录,请设置密码"
              description={`账号 ${pendingEmail} 尚未设置密码,请输入管理员提供的激活码并设置密码。`}
            />
            <Form form={setForm} layout="vertical" onFinish={doSetPassword} disabled={loading}>
              <Form.Item label="邮箱">
                <Input prefix={<MailOutlined />} value={pendingEmail} disabled />
              </Form.Item>
              <Form.Item
                name="code"
                label="激活码"
                rules={[{ required: true, message: '请输入管理员提供的激活码' }]}
              >
                <Input prefix={<SafetyOutlined />} placeholder="管理员提供的激活码" />
              </Form.Item>
              <Form.Item
                name="password"
                label="设置密码"
                rules={[
                  { required: true, message: '请输入密码' },
                  { min: 6, message: '密码至少 6 位' },
                ]}
              >
                  <Input.Password prefix={<LockOutlined />} placeholder="至少 6 位" autoComplete="new-password" />
                </Form.Item>
                <Form.Item
                  name="confirm"
                  label="确认密码"
                  dependencies={['password']}
                  rules={[
                    { required: true, message: '请再次输入密码' },
                    ({ getFieldValue }) => ({
                      validator(_, value) {
                        if (!value || getFieldValue('password') === value) return Promise.resolve()
                        return Promise.reject(new Error('两次输入的密码不一致'))
                      },
                    }),
                  ]}
                >
                  <Input.Password prefix={<LockOutlined />} placeholder="再次输入密码" autoComplete="new-password" />
                </Form.Item>
                <Button type="primary" htmlType="submit" block loading={loading}>
                  设置密码并登录
                </Button>
                <Button
                  type="link"
                  block
                  style={{ marginTop: 8 }}
                  onClick={() => {
                    setMode('login')
                    setPendingEmail('')
                    setForm.resetFields()
                  }}
                >
                  返回登录
                </Button>
              </Form>
            </>
          ) : (
            <>
              <Form form={loginForm} layout="vertical" onFinish={doLogin} disabled={loading}>
                <Form.Item
                  name="email"
                  label="邮箱"
                  rules={[
                    { required: true, message: '请输入邮箱' },
                    { type: 'email', message: '邮箱格式不正确' },
                  ]}
                >
                  <Input prefix={<MailOutlined />} placeholder="you@example.com" autoComplete="username" />
                </Form.Item>
                <Form.Item name="password" label="密码" rules={[{ required: true, message: '请输入密码' }]}>
                  <Input.Password
                    prefix={<LockOutlined />}
                    placeholder="请输入密码"
                    autoComplete="current-password"
                  />
                </Form.Item>
                <Button type="primary" htmlType="submit" block loading={loading}>
                  登录
                </Button>
              </Form>
            </>
          )}
        </section>
      </div>
    </div>
  )
}
