import { useCallback, useEffect, useState } from 'react'
import {
  App as AntApp,
  Button,
  Card,
  Drawer,
  Empty,
  Form,
  Input,
  List,
  Modal,
  Popconfirm,
  Space,
  Table,
  Tag,
  Tooltip,
  Typography,
  Upload,
} from 'antd'
import {
  DeleteOutlined,
  InboxOutlined,
  PlusOutlined,
  ReloadOutlined,
  RobotOutlined,
  UploadOutlined,
} from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { api, del, errMsg, get, post, LibraryDoc, LibraryItem, User } from '../api/client'

/**
 * 资料库:所有用户共享。
 * 先新建「资料」(名称唯一 + 描述),再在其下上传已有系统文档;
 * 系统夜间把该资料下的文档整理成 AI 分析,回填到该资料,供其他项目按名称参考。
 */
export default function Library({ me }: { me: User }) {
  const { message } = AntApp.useApp()
  const [items, setItems] = useState<LibraryItem[]>([])
  const [loading, setLoading] = useState(true)
  const [open, setOpen] = useState(false)
  const [saving, setSaving] = useState(false)
  const [form] = Form.useForm()
  const [current, setCurrent] = useState<LibraryItem | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [analyzing, setAnalyzing] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const data = await get<LibraryItem[]>('/api/library/items')
      setItems(Array.isArray(data) ? data : [])
    } catch (e) {
      message.error(errMsg(e))
      setItems([])
    } finally {
      setLoading(false)
    }
  }, [message])

  useEffect(() => {
    load()
  }, [load])

  const canManage = (it: LibraryItem) => me.role === 'admin' || me.id === it.createdBy

  async function createItem() {
    let v: any
    try {
      v = await form.validateFields()
    } catch {
      return
    }
    setSaving(true)
    try {
      await post<LibraryItem>('/api/library/items', {
        name: (v.name || '').trim(),
        description: v.description || '',
      })
      message.success('资料已创建')
      setOpen(false)
      form.resetFields()
      load()
    } catch (e) {
      message.error(errMsg(e))
    } finally {
      setSaving(false)
    }
  }

  async function openDetail(item: LibraryItem) {
    setCurrent(item)
    setDetailLoading(true)
    try {
      setCurrent(await get<LibraryItem>(`/api/library/items/${item.id}`))
    } catch (e) {
      message.error(errMsg(e))
    } finally {
      setDetailLoading(false)
    }
  }

  async function removeItem(it: LibraryItem) {
    try {
      await del(`/api/library/items/${it.id}`)
      message.success('资料已删除')
      if (current?.id === it.id) setCurrent(null)
      load()
    } catch (e) {
      message.error(errMsg(e))
    }
  }

  async function uploadDoc(it: LibraryItem, options: any) {
    const { file, onSuccess, onError } = options
    const fd = new FormData()
    fd.append('file', file)
    try {
      await api.post(`/api/library/items/${it.id}/documents`, fd)
      message.success(`已上传:${file?.name || ''},将在夜间整理`)
      onSuccess?.({})
      openDetail(it)
      load()
    } catch (e) {
      message.error(errMsg(e))
      onError?.(e)
    }
  }

  async function removeDoc(it: LibraryItem, d: LibraryDoc) {
    try {
      await del(`/api/library/documents/${d.id}`)
      message.success('文档已删除')
      openDetail(it)
      load()
    } catch (e) {
      message.error(errMsg(e))
    }
  }

  async function analyze(it: LibraryItem) {
    setAnalyzing(true)
    try {
      const updated = await post<LibraryItem>(`/api/library/items/${it.id}/analyze`)
      setCurrent(updated)
      message.success('整理完成')
      load()
    } catch (e) {
      message.error(errMsg(e))
    } finally {
      setAnalyzing(false)
    }
  }

  const columns: ColumnsType<LibraryItem> = [
    {
      title: '资料名称',
      dataIndex: 'name',
      key: 'name',
      render: (text: string, it) => <a onClick={() => openDetail(it)}>{text}</a>,
    },
    {
      title: '资料描述',
      dataIndex: 'description',
      key: 'description',
      render: (v: string) => (
        <Typography.Text type={v ? undefined : 'secondary'} ellipsis={{ tooltip: v }}>
          {v || '-'}
        </Typography.Text>
      ),
    },
    {
      title: '文档数',
      dataIndex: 'docCount',
      key: 'docCount',
      width: 90,
      align: 'center',
    },
    {
      title: 'AI 整理',
      key: 'analysis',
      width: 120,
      render: (_, it) =>
        it.analysisReady ? (
          <Tag color="green">已整理</Tag>
        ) : it.analysisError ? (
          <Tooltip title={it.analysisError}>
            <Tag color="red">整理失败</Tag>
          </Tooltip>
        ) : (
          <Tag>待整理</Tag>
        ),
    },
    {
      title: '操作',
      key: 'actions',
      width: 150,
      render: (_, it) => (
        <Space>
          <Button size="small" type="link" onClick={() => openDetail(it)}>
            查看
          </Button>
          {canManage(it) ? (
            <Popconfirm
              title="确认删除该资料?"
              description="其下所有文档与 AI 整理结果将一并删除,且不可恢复。"
              okText="删除"
              okButtonProps={{ danger: true }}
              cancelText="取消"
              onConfirm={() => removeItem(it)}
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
    <div>
      <Card
        title="资料库"
        extra={
          <Space>
            <Button icon={<ReloadOutlined />} onClick={load}>
              刷新
            </Button>
            <Button type="primary" icon={<PlusOutlined />} onClick={() => setOpen(true)}>
              新建资料
            </Button>
          </Space>
        }
      >
        <Typography.Paragraph type="secondary" style={{ marginTop: 0 }}>
          每份资料填一个<strong>名称(唯一)</strong>与<strong>描述</strong>,再在其下上传已有系统的文档。
          系统每天夜间会把资料下的文档整理成 AI 分析,供<strong>所有项目</strong>按名称勾选参考。
        </Typography.Paragraph>
        <Table<LibraryItem>
          rowKey="id"
          columns={columns}
          dataSource={items}
          loading={loading}
          locale={{
            emptyText: (
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description="还没有资料,新建第一份开始吧"
              >
                <Button type="primary" icon={<PlusOutlined />} onClick={() => setOpen(true)}>
                  新建资料
                </Button>
              </Empty>
            ),
          }}
        />
      </Card>

      <Modal
        title="新建资料"
        open={open}
        onOk={createItem}
        confirmLoading={saving}
        onCancel={() => setOpen(false)}
        okText="创建"
        cancelText="取消"
        destroyOnClose
      >
        <Form form={form} layout="vertical" preserve={false}>
          <Form.Item
            name="name"
            label="资料名称"
            rules={[{ required: true, message: '请输入资料名称' }, { max: 64, message: '最长 64 字' }]}
          >
            <Input placeholder="例如:嘉南纺织 ERP 旧系统" maxLength={64} />
          </Form.Item>
          <Form.Item name="description" label="资料描述">
            <Input.TextArea
              rows={3}
              maxLength={1000}
              showCount
              placeholder="简单说明这份资料是什么、包含哪些内容"
            />
          </Form.Item>
        </Form>
      </Modal>

      <Drawer
        width={720}
        open={!!current}
        onClose={() => setCurrent(null)}
        title={current?.name || '资料详情'}
        destroyOnClose
      >
        {current ? (
          <div>
            <Typography.Paragraph type="secondary" style={{ marginTop: 0 }}>
              {current.description || '（无描述）'}
            </Typography.Paragraph>

            <Card
              size="small"
              title="资料文档"
              style={{ marginBottom: 12 }}
              extra={
                canManage(current) ? (
                  <Upload
                    multiple
                    showUploadList={false}
                    accept=".docx,.xlsx,.xlsm,.pdf,.txt,.md,.csv,.json,.log,.yaml,.yml"
                    customRequest={(o) => uploadDoc(current, o)}
                  >
                    <Button size="small" icon={<UploadOutlined />}>
                      上传文档
                    </Button>
                  </Upload>
                ) : null
              }
            >
              {current.docs.length ? (
                <List
                  size="small"
                  loading={detailLoading}
                  dataSource={current.docs}
                  renderItem={(d) => (
                    <List.Item
                      actions={
                        canManage(current)
                          ? [
                              <Button
                                key="del"
                                type="link"
                                danger
                                size="small"
                                icon={<DeleteOutlined />}
                                onClick={() => removeDoc(current, d)}
                              >
                                删除
                              </Button>,
                            ]
                          : []
                      }
                    >
                      <List.Item.Meta
                        title={<span>{d.filename}</span>}
                        description={d.createdAt || ''}
                      />
                    </List.Item>
                  )}
                />
              ) : (
                <Upload.Dragger
                  multiple
                  disabled={!canManage(current)}
                  customRequest={(o) => uploadDoc(current, o)}
                  showUploadList={false}
                  accept=".docx,.xlsx,.xlsm,.pdf,.txt,.md,.csv,.json,.log,.yaml,.yml"
                >
                  <p className="ant-upload-drag-icon">
                    <InboxOutlined />
                  </p>
                  <p className="ant-upload-text">点击或拖拽文件到此区域上传</p>
                  <p className="ant-upload-hint">
                    支持 Word / Excel / PDF / 文本 / Markdown,可一次选择多个文件
                  </p>
                </Upload.Dragger>
              )}
            </Card>

            <Card
              size="small"
              title="AI 整理内容"
              extra={
                canManage(current) ? (
                  <Button
                    size="small"
                    icon={<RobotOutlined />}
                    loading={analyzing}
                    disabled={!current.docCount}
                    onClick={() => analyze(current)}
                  >
                    立即整理
                  </Button>
                ) : null
              }
            >
              {current.analysisReady ? (
                <div className="md-body">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>{current.analysis || ''}</ReactMarkdown>
                </div>
              ) : (
                <Empty
                  image={Empty.PRESENTED_IMAGE_SIMPLE}
                  description={
                    current.analysisError
                      ? `上次整理失败:${current.analysisError}`
                      : '尚未整理,系统会在夜间自动整理,也可点「立即整理」'
                  }
                />
              )}
              {current.analysisAt ? (
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  整理时间:{current.analysisAt}
                </Typography.Text>
              ) : null}
            </Card>
          </div>
        ) : null}
      </Drawer>
    </div>
  )
}
