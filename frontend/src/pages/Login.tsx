import { useEffect, useState } from 'react'
import { Alert, App as AntApp, Button, Card, Form, Input, Spin, Typography } from 'antd'
import { LockOutlined, MailOutlined, UserOutlined, ThunderboltOutlined } from '@ant-design/icons'
import { errMsg, get, HealthInfo, post, User } from '../api/client'

export default function Login({ onLoggedIn }: { onLoggedIn: (u: User) => void }) {
  const { message } = AntApp.useApp()
  const [checking, setChecking] = useState(true)
  const [needsBootstrap, setNeedsBootstrap] = useState(false)
  const [backendDown, setBackendDown] = useState(false)
  const [loading, setLoading] = useState(false)
  const [loginForm] = Form.useForm()
  const [bootForm] = Form.useForm()

  useEffect(() => {
    get<HealthInfo>('/api/health')
      .then((h) => {
        setNeedsBootstrap(!!h?.needsBootstrap)
        setBackendDown(false)
      })
      .catch(() => setBackendDown(true))
      .finally(() => setChecking(false))
  }, [])

  async function finishLogin(email: string, password: string) {
    await post('/api/auth/login', { email, password })
    const me = await get<User>('/api/auth/me')
    message.success('登录成功')
    onLoggedIn(me)
  }

  async function doLogin(values: any) {
    setLoading(true)
    try {
      await finishLogin(values.email, values.password)
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
        displayName: values.displayName || values.email,
      })
      await finishLogin(values.email, values.password)
    } catch (e) {
      message.error(errMsg(e))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="login-page">
      <Card className="login-card">
        <div style={{ textAlign: 'center', marginBottom: 20 }}>
          <ThunderboltOutlined style={{ fontSize: 32, color: '#1677ff' }} />
          <Typography.Title level={3} style={{ margin: '8px 0 0' }}>
            h3factory
          </Typography.Title>
          <Typography.Text type="secondary">氚云应用智能生成平台</Typography.Text>
        </div>

        {backendDown ? (
          <Alert
            type="warning"
            showIcon
            style={{ marginBottom: 16 }}
            message="无法连接后端服务"
            description="请确认后端已在 http://localhost:8000 启动后重试。"
          />
        ) : null}

        {checking ? (
          <div style={{ textAlign: 'center', padding: 24 }}>
            <Spin />
          </div>
        ) : needsBootstrap ? (
          <>
            <Alert
              type="info"
              showIcon
              style={{ marginBottom: 16 }}
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
              <Form.Item name="displayName" label="显示名称">
                <Input prefix={<UserOutlined />} placeholder="管理员" />
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
      </Card>
    </div>
  )
}
