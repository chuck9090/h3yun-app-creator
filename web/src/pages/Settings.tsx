import { useEffect, useState } from 'react'
import { Alert, App as AntApp, Button, Card, Form, Input, Space, Spin, Tag, Typography } from 'antd'
import { ReloadOutlined, SaveOutlined } from '@ant-design/icons'
import { errMsg, get, put } from '../api/client'

interface LLMSettings {
  baseUrl?: string
  model?: string
  hasKey?: boolean
}

export default function Settings() {
  const { message } = AntApp.useApp()
  const [form] = Form.useForm()
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [hasKey, setHasKey] = useState(false)

  async function load() {
    setLoading(true)
    try {
      const s = await get<LLMSettings>('/api/settings/llm')
      form.setFieldsValue({
        baseUrl: s?.baseUrl || '',
        model: s?.model || '',
        apiKey: '',
      })
      setHasKey(!!s?.hasKey)
    } catch (e) {
      message.error(errMsg(e))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  async function save() {
    let v: any
    try {
      v = await form.validateFields()
    } catch {
      return
    }
    setSaving(true)
    try {
      await put('/api/settings/llm', {
        baseUrl: v.baseUrl || '',
        apiKey: v.apiKey || '',
        model: v.model || '',
      })
      message.success('LLM 设置已保存')
      await load()
    } catch (e) {
      message.error(errMsg(e))
    } finally {
      setSaving(false)
    }
  }

  return (
    <Card
      title="系统设置 · 大模型(LLM)"
      extra={
        <Space>
          <Button icon={<ReloadOutlined />} onClick={load}>
            刷新
          </Button>
          <Button type="primary" icon={<SaveOutlined />} loading={saving} onClick={save}>
            保存
          </Button>
        </Space>
      }
    >
      {loading ? (
        <div style={{ textAlign: 'center', padding: 24 }}>
          <Spin />
        </div>
      ) : (
        <>
          <Alert
            type="info"
            showIcon
            style={{ marginBottom: 12 }}
            message="配置 OpenAI 兼容接口即可启用大模型;留空则使用启发式生成。"
            description="Base URL 例如 https://api.openai.com/v1 或任意兼容服务地址;API Key 仅加密存储,不会回显。"
          />
          <Form form={form} layout="vertical" style={{ maxWidth: 560 }}>
            <Form.Item name="baseUrl" label="Base URL">
              <Input placeholder="https://api.openai.com/v1" />
            </Form.Item>
            <Form.Item label="API Key" extra={hasKey ? '已配置,留空表示不修改' : '尚未配置'}>
              <Space.Compact style={{ width: '100%' }}>
                <Form.Item name="apiKey" noStyle>
                  <Input.Password placeholder={hasKey ? '••••••••(留空不修改)' : 'sk-...'} />
                </Form.Item>
                {hasKey ? <Tag color="green" style={{ marginLeft: 8, lineHeight: '30px' }}>已配置</Tag> : null}
              </Space.Compact>
            </Form.Item>
            <Form.Item name="model" label="模型名称">
              <Input placeholder="例如 gpt-4o-mini / qwen-plus" />
            </Form.Item>
            <Typography.Text type="secondary">
              保存后立即生效,下一次生成方案 / 业务流程图 / ER 设计时使用。
            </Typography.Text>
          </Form>
        </>
      )}
    </Card>
  )
}
