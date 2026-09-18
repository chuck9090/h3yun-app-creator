import { useCallback, useEffect, useState } from 'react'
import {
  Alert,
  App as AntApp,
  Button,
  Card,
  Divider,
  Empty,
  List,
  Select,
  Space,
  Tag,
  Typography,
  Upload,
} from 'antd'
import { DeleteOutlined, InboxOutlined, SaveOutlined } from '@ant-design/icons'
import ReactQuill from 'react-quill'
import { api, del, DOC_KINDS, DocumentItem, errMsg, get, put } from '../api/client'

const QUILL_MODULES = {
  toolbar: [
    [{ header: [1, 2, 3, false] }],
    ['bold', 'italic', 'underline', 'strike'],
    [{ list: 'ordered' }, { list: 'bullet' }],
    ['blockquote', 'link'],
    ['clean'],
  ],
}

const QUILL_FORMATS = [
  'header',
  'bold',
  'italic',
  'underline',
  'strike',
  'list',
  'bullet',
  'blockquote',
  'link',
]

function stripHtml(html: string): string {
  return (html || '')
    .replace(/<[^>]+>/g, ' ')
    .replace(/&nbsp;/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
}

function kindLabel(kind: string): string {
  return DOC_KINDS.find((k) => k.value === kind)?.label || kind
}

export default function RequirementStep({
  projectId,
  canWrite,
}: {
  projectId: number
  canWrite: boolean
}) {
  const { message } = AntApp.useApp()
  const [kind, setKind] = useState<string>('requirement')
  const [docs, setDocs] = useState<DocumentItem[]>([])
  const [docsLoading, setDocsLoading] = useState(false)
  const [html, setHtml] = useState('')
  const [loadingReq, setLoadingReq] = useState(false)
  const [saving, setSaving] = useState(false)

  const loadDocs = useCallback(async () => {
    setDocsLoading(true)
    try {
      const data = await get<DocumentItem[]>(`/api/projects/${projectId}/documents`)
      setDocs(Array.isArray(data) ? data : [])
    } catch (e) {
      message.error(errMsg(e))
      setDocs([])
    } finally {
      setDocsLoading(false)
    }
  }, [projectId, message])

  useEffect(() => {
    loadDocs()
  }, [loadDocs])

  useEffect(() => {
    setLoadingReq(true)
    get<{ html?: string; text?: string }>(`/api/projects/${projectId}/requirement`)
      .then((r) => setHtml(r?.html || ''))
      .catch(() => setHtml(''))
      .finally(() => setLoadingReq(false))
  }, [projectId])

  const customRequest = async (options: any) => {
    const { file, onSuccess, onError } = options
    const fd = new FormData()
    fd.append('file', file)
    fd.append('kind', kind)
    try {
      await api.post(`/api/projects/${projectId}/documents`, fd)
      message.success(`已上传:${file?.name || ''}`)
      onSuccess?.({})
      loadDocs()
    } catch (e) {
      message.error(errMsg(e))
      onError?.(e)
    }
  }

  async function removeDoc(doc: DocumentItem) {
    try {
      await del(`/api/documents/${doc.id}`)
      message.success('文档已删除')
      loadDocs()
    } catch (e) {
      message.error(errMsg(e))
    }
  }

  async function saveRequirement() {
    setSaving(true)
    try {
      await put(`/api/projects/${projectId}/requirement`, { html, text: stripHtml(html) })
      message.success('需求已保存')
    } catch (e) {
      message.error(errMsg(e))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div>
      <Card title="上传需求资料" style={{ marginBottom: 16 }}>
        <Typography.Paragraph type="secondary" style={{ marginTop: 0 }}>
          支持拖拽上传 Word / Excel / PDF / 文本 / Markdown 等,系统会自动解析内容供 AI 使用。
        </Typography.Paragraph>
        <Space style={{ marginBottom: 12 }} wrap>
          <span>资料类型:</span>
          <Select
            value={kind}
            onChange={setKind}
            style={{ width: 180 }}
            options={DOC_KINDS.map((k) => ({ value: k.value, label: k.label }))}
            disabled={!canWrite}
          />
        </Space>
        <Upload.Dragger
          multiple
          disabled={!canWrite}
          customRequest={customRequest}
          showUploadList={false}
          accept=".doc,.docx,.xls,.xlsx,.pdf,.txt,.md,.csv,.json"
        >
          <p className="ant-upload-drag-icon">
            <InboxOutlined />
          </p>
          <p className="ant-upload-text">点击或拖拽文件到此区域上传</p>
          <p className="ant-upload-hint">可一次选择多个文件</p>
        </Upload.Dragger>

        <Divider orientation="left" plain>
          已上传文档
        </Divider>
        {docs.length ? (
          <List
            size="small"
            loading={docsLoading}
            dataSource={docs}
            renderItem={(doc) => (
              <List.Item
                actions={
                  canWrite
                    ? [
                        <Button
                          key="del"
                          type="link"
                          danger
                          size="small"
                          icon={<DeleteOutlined />}
                          onClick={() => removeDoc(doc)}
                        >
                          删除
                        </Button>,
                      ]
                    : []
                }
              >
                <List.Item.Meta
                  title={
                    <Space>
                      <span>{doc.filename}</span>
                      <Tag>{kindLabel(doc.kind)}</Tag>
                      {doc.status ? <Tag color="blue">{doc.status}</Tag> : null}
                    </Space>
                  }
                  description={doc.summary || doc.createdAt || ''}
                />
              </List.Item>
            )}
          />
        ) : (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无文档" />
        )}
      </Card>

      <Card
        title="富文本需求"
        extra={
          canWrite ? (
            <Button type="primary" icon={<SaveOutlined />} loading={saving} onClick={saveRequirement}>
              保存需求
            </Button>
          ) : null
        }
      >
        {loadingReq ? (
          <div style={{ padding: 24 }}>
            <Alert type="info" message="正在加载需求内容..." showIcon />
          </div>
        ) : (
          <div data-color-mode="light">
            <ReactQuill
              theme="snow"
              value={html}
              onChange={setHtml}
              readOnly={!canWrite}
              modules={QUILL_MODULES}
              formats={QUILL_FORMATS}
              placeholder="在此补充业务背景、目标、范围、角色、关键流程等。"
            />
          </div>
        )}
      </Card>
    </div>
  )
}
