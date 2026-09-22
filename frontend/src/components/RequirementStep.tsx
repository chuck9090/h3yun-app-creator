import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Alert,
  App as AntApp,
  Button,
  Card,
  Checkbox,
  Col,
  Divider,
  Empty,
  List,
  Row,
  Select,
  Space,
  Tag,
  Typography,
  Upload,
} from 'antd'
import { DeleteOutlined, InboxOutlined, SaveOutlined } from '@ant-design/icons'
import ReactQuill from 'react-quill'
import {
  api,
  del,
  DOC_KIND_LABELS,
  DOC_KINDS,
  DocumentItem,
  errMsg,
  get,
  ProjectRefDocs,
  put,
} from '../api/client'
import { useTheme } from '../theme/ThemeContext'

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
  return DOC_KIND_LABELS[kind] || kind
}

export default function RequirementStep({
  projectId,
  canWrite,
}: {
  projectId: number
  canWrite: boolean
}) {
  const { message } = AntApp.useApp()
  const { dark } = useTheme()
  const nav = useNavigate()
  const [kind, setKind] = useState<string>('requirement')
  const [docs, setDocs] = useState<DocumentItem[]>([])
  const [docsLoading, setDocsLoading] = useState(false)
  const [html, setHtml] = useState('')
  const [loadingReq, setLoadingReq] = useState(false)
  const [saving, setSaving] = useState(false)
  const [refIds, setRefIds] = useState<number[]>([])
  const [library, setLibrary] = useState<ProjectRefDocs['library']>([])

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

  useEffect(() => {
    get<ProjectRefDocs>(`/api/projects/${projectId}/ref-docs`)
      .then((r) => {
        setRefIds(r?.ids || [])
        setLibrary(r?.library || [])
      })
      .catch(() => {
        setRefIds([])
        setLibrary([])
      })
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

  async function saveRefDocs(ids: number[]) {
    setRefIds(ids)
    try {
      await put(`/api/projects/${projectId}/ref-docs`, { ids })
      message.success('参考资料已更新')
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
      <Card
        title="额外补充信息"
        style={{ marginBottom: 12 }}
        extra={
          canWrite ? (
            <Button type="primary" icon={<SaveOutlined />} loading={saving} onClick={saveRequirement}>
              保存
            </Button>
          ) : null
        }
      >
        {loadingReq ? (
          <div style={{ padding: 16 }}>
            <Alert type="info" message="正在加载内容..." showIcon />
          </div>
        ) : (
          <div data-color-mode={dark ? 'dark' : 'light'}>
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

      <Row gutter={12}>
        <Col span={12}>
          <Card title="上传需求资料" style={{ height: '100%' }}>
            <Typography.Paragraph type="secondary" style={{ marginTop: 0 }}>
              上传本项目专用的需求 / 会议等资料,系统会自动解析内容供 AI 使用。
              已有系统的资料请到左侧「资料库」统一维护,再在右侧勾选参考。
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
              accept=".docx,.xlsx,.xlsm,.pdf,.txt,.md,.csv,.json,.log,.yaml,.yml"
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
        </Col>

        <Col span={12}>
          <Card
            title="参考资料(来自资料库)"
            style={{ height: '100%' }}
            extra={canWrite ? <a onClick={() => nav('/library')}>去资料库</a> : null}
          >
            <Typography.Paragraph type="secondary" style={{ marginTop: 0 }}>
              勾选后,生成「系统设计方案」与「ER 结构」时会参考这些共享资料;资料由系统夜间统一整理。
            </Typography.Paragraph>
            {library.length ? (
              <Checkbox.Group
                value={refIds}
                disabled={!canWrite}
                onChange={(v) => saveRefDocs(v as number[])}
                style={{ display: 'block' }}
              >
                <Space direction="vertical" size={6}>
                  {library.map((it) => (
                    <Checkbox key={it.id} value={it.id}>
                      <Space size={6} wrap>
                        <span>{it.name}</span>
                        {it.analysisReady ? <Tag color="green">已整理</Tag> : <Tag>待整理</Tag>}
                        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                          {it.docCount} 份文档
                          {it.description
                            ? ` · ${it.description.length > 40 ? `${it.description.slice(0, 40)}…` : it.description}`
                            : ''}
                        </Typography.Text>
                      </Space>
                    </Checkbox>
                  ))}
                </Space>
              </Checkbox.Group>
            ) : (
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description="资料库暂无资料,可到「资料库」新建资料并上传文档"
              />
            )}
          </Card>
        </Col>
      </Row>
    </div>
  )
}
