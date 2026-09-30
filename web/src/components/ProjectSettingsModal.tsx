import { useEffect, useState } from 'react'
import { App as AntApp, Form, Input, Modal, Typography } from 'antd'
import { errMsg, patch, Project } from '../api/client'

export default function ProjectSettingsModal({
  open,
  project,
  onClose,
  onSaved,
}: {
  open: boolean
  project: Project | null
  onClose: () => void
  onSaved?: () => void
}) {
  const { message } = AntApp.useApp()
  const [form] = Form.useForm()
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (!open) return
    form.setFieldsValue({
      title: project?.title || '',
      engineCode: project?.engineCode || '',
      appCode: project?.appCode || '',
      h3Token: '',
    })
  }, [open, project, form])

  async function submit() {
    let v: any
    try {
      v = await form.validateFields()
    } catch {
      return
    }
    if (!project) return
    const payload: Record<string, any> = {}
    if (v.title && v.title !== project.title) payload.title = v.title
    if (v.engineCode && v.engineCode !== project.engineCode) payload.engineCode = v.engineCode
    if (v.appCode && v.appCode !== project.appCode) payload.appCode = v.appCode
    if (v.h3Token) payload.h3Token = v.h3Token
    if (!Object.keys(payload).length) {
      message.info('没有需要修改的内容')
      onClose()
      return
    }
    setSaving(true)
    try {
      await patch(`/api/projects/${project.id}`, payload)
      message.success('项目设置已保存')
      onClose()
      onSaved?.()
    } catch (e) {
      message.error(errMsg(e))
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal
      title="项目设置"
      open={open}
      onOk={submit}
      confirmLoading={saving}
      onCancel={onClose}
      okText="保存"
      cancelText="取消"
      width={620}
      destroyOnClose
    >
      <Form form={form} layout="vertical" preserve={false}>
        <Form.Item name="title" label="项目名称">
          <Input placeholder="项目显示名称" maxLength={120} />
        </Form.Item>
        <Form.Item
          name="engineCode"
          label="引擎编码(engineCode)"
          tooltip="氚云引擎编码;粘贴 h3_token 可自动带出"
        >
          <Input placeholder="留空表示不修改" maxLength={64} />
        </Form.Item>
        <Form.Item
          name="appCode"
          label="应用编码(appCode)"
          tooltip="氚云后台创建应用后,复制其应用编码填入;本系统不自动创建应用"
        >
          <Input placeholder="留空表示不修改" maxLength={64} />
        </Form.Item>
        <Form.Item
          name="h3Token"
          label="h3_token"
          tooltip="粘贴新的氚云 h3_token(JWT);留空表示不修改"
        >
          <Input.TextArea rows={4} placeholder="留空表示不修改"
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
        <Typography.Text type="secondary">
          留空的字段不会被修改;h3_token 加密存储且绝不回显。
        </Typography.Text>
      </Form>
    </Modal>
  )
}
