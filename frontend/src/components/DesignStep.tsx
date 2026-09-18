import { useCallback, useEffect, useRef, useState } from 'react'
import {
  Alert,
  App as AntApp,
  Button,
  Card,
  Collapse,
  Empty,
  Input,
  Select,
  Space,
  Switch,
  Table,
  Tabs,
  Tag,
  Typography,
} from 'antd'
import {
  DeleteOutlined,
  PlusOutlined,
  ReloadOutlined,
  RobotOutlined,
  SaveOutlined,
} from '@ant-design/icons'
import AutomationEditor from './AutomationEditor'
import GroupsEditor from './GroupsEditor'
import {
  Background,
  Controls,
  MarkerType,
  MiniMap,
  ReactFlow,
  useEdgesState,
  useNodesState,
  type Edge,
  type Node,
} from '@xyflow/react'
import ErNode from './ErNode'
import {
  Automation,
  COLUMN_TYPES,
  CONTROL_TYPES,
  Control,
  Design,
  ErEdge,
  errMsg,
  get,
  post,
  put,
  Sheet,
  validateAutomations,
} from '../api/client'

const nodeTypes = { er: ErNode }

const DICT_TYPES = ['dropdown', 'radio', 'checkbox_list']

function normalizeSheets(list: any): Sheet[] {
  return (Array.isArray(list) ? list : [])
    .filter((s) => s && s.key)
    .map((s) => ({
      key: s.key,
      title: s.title || s.key,
      nameSchema: s.nameSchema || '',
      useOwner: !!s.useOwner,
      group: s.group || '',
      layout: s.layout || 'auto4',
      controls: Array.isArray(s.controls) ? s.controls : [],
    }))
}

function normalizeAutomations(list: any): Automation[] {
  return (Array.isArray(list) ? list : [])
    .filter((a) => a && typeof a === 'object')
    .map((a) => ({
      key: a.key || '',
      title: a.title || '',
      form: a.form || '',
      trigger: a.trigger || '生效',
      sortKey: typeof a.sortKey === 'number' ? a.sortKey : undefined,
      names: a.names || undefined,
      when: Array.isArray(a.when) ? a.when : [],
      actions: Array.isArray(a.actions) ? a.actions : [],
    }))
}

export default function DesignStep({
  projectId,
  canWrite,
  onGenerated,
  gate,
}: {
  projectId: number
  canWrite: boolean
  onGenerated?: (key: string) => void
  gate?: string
}) {
  const { message } = AntApp.useApp()
  const [sheets, setSheets] = useState<Sheet[]>([])
  const [dicts, setDicts] = useState<Record<string, any[]>>({})
  const [groups, setGroups] = useState<any[]>([])
  const [automations, setAutomations] = useState<Automation[]>([])
  const [edges, setEdges] = useState<ErEdge[]>([])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [generating, setGenerating] = useState(false)
  const [check, setCheck] = useState<any>(null)
  const [checking, setChecking] = useState(false)

  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([])
  const [flowEdges, setFlowEdges, onEdgesChange] = useEdgesState<Edge>([])
  const posRef = useRef<Record<string, { x: number; y: number }>>({})

  const loadEr = useCallback(async () => {
    try {
      const g = await get<{ edges?: ErEdge[] }>(`/api/projects/${projectId}/design/er`)
      setEdges(Array.isArray(g?.edges) ? g.edges : [])
    } catch {
      setEdges([])
    }
  }, [projectId])

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const d = await get<Design>(`/api/projects/${projectId}/design`)
      setSheets(normalizeSheets(d?.sheets))
      setDicts(d?.dicts || {})
      setGroups(Array.isArray(d?.groups) ? d.groups : [])
      setAutomations(normalizeAutomations(d?.automations))
      await loadEr()
    } catch (e) {
      message.error(errMsg(e))
      setSheets([])
    } finally {
      setLoading(false)
    }
  }, [projectId, message, loadEr])

  useEffect(() => {
    load()
  }, [load])

  useEffect(() => {
    setNodes(
      sheets.map((s, i) => ({
        id: s.key,
        type: 'er',
        position: posRef.current[s.key] || { x: (i % 3) * 300, y: Math.floor(i / 3) * 380 },
        data: { title: s.title, key: s.key, fields: s.controls || [] },
      })),
    )
  }, [sheets, setNodes])

  useEffect(() => {
    const valid = new Set(sheets.map((s) => s.key))
    setFlowEdges(
      edges
        .filter((e) => e && e.source && e.target && valid.has(e.source) && valid.has(e.target))
        .map((e, i) => ({
          id: `${e.source}-${e.target}-${e.field || i}`,
          source: e.source,
          target: e.target,
          label: e.label || e.field || '',
          type: 'smoothstep',
          animated: e.kind === '联动',
          style: { stroke: '#1677ff' },
          markerEnd: { type: MarkerType.ArrowClosed },
        })),
    )
  }, [edges, sheets, setFlowEdges])

  /* -------------------------------------------------- 编辑操作 */
  function updateSheet(idx: number, patch: Partial<Sheet>) {
    setSheets((prev) => prev.map((s, i) => (i === idx ? { ...s, ...patch } : s)))
  }

  function updateControl(si: number, ci: number, patch: Partial<Control>) {
    setSheets((prev) =>
      prev.map((s, i) => {
        if (i !== si) return s
        return { ...s, controls: s.controls.map((c, j) => (j === ci ? { ...c, ...patch } : c)) }
      }),
    )
  }

  function addControl(si: number) {
    setSheets((prev) =>
      prev.map((s, i) =>
        i === si
          ? {
              ...s,
              controls: [...s.controls, { type: 'text', key: '', label: '' } as Control],
            }
          : s,
      ),
    )
  }

  function removeControl(si: number, ci: number) {
    setSheets((prev) =>
      prev.map((s, i) =>
        i === si ? { ...s, controls: s.controls.filter((_, j) => j !== ci) } : s,
      ),
    )
  }

  function addSheet() {
    let n = sheets.length + 1
    let key = `table${n}`
    const exists = new Set(sheets.map((s) => s.key))
    while (exists.has(key)) {
      n += 1
      key = `table${n}`
    }
    setSheets((prev) => [
      ...prev,
      { key, title: '新表', nameSchema: '', useOwner: false, group: '', layout: 'auto4', controls: [] },
    ])
  }

  function removeSheet(si: number) {
    setSheets((prev) => prev.filter((_, i) => i !== si))
  }

  function updateColumn(si: number, ci: number, coli: number, patch: Partial<Control>) {
    setSheets((prev) =>
      prev.map((s, i) => {
        if (i !== si) return s
        return {
          ...s,
          controls: s.controls.map((c, j) => {
            if (j !== ci) return c
            const columns = (c.columns || []).map((col, k) =>
              k === coli ? { ...col, ...patch } : col,
            )
            return { ...c, columns }
          }),
        }
      }),
    )
  }

  function addColumn(si: number, ci: number) {
    setSheets((prev) =>
      prev.map((s, i) => {
        if (i !== si) return s
        return {
          ...s,
          controls: s.controls.map((c, j) =>
            j === ci
              ? {
                  ...c,
                  columns: [...(c.columns || []), { type: 'text', key: '', label: '' } as Control],
                }
              : c,
          ),
        }
      }),
    )
  }

  function removeColumn(si: number, ci: number, coli: number) {
    setSheets((prev) =>
      prev.map((s, i) => {
        if (i !== si) return s
        return {
          ...s,
          controls: s.controls.map((c, j) =>
            j === ci ? { ...c, columns: (c.columns || []).filter((_, k) => k !== coli) } : c,
          ),
        }
      }),
    )
  }

  /* -------------------------------------------------- 远端操作 */
  async function runCheck() {
    setChecking(true)
    try {
      // 契约:GET /design/check 的 data 就是 check 结果本身(单层,不再裹 check)。
      const r = await get<any>(`/api/projects/${projectId}/design/check`)
      setCheck(r?.check ?? r)
    } catch (e) {
      setCheck({ error: errMsg(e) })
    } finally {
      setChecking(false)
    }
  }

  async function generate() {
    setGenerating(true)
    try {
      const r = await post<any>(`/api/projects/${projectId}/design/generate`, {})
      if (Array.isArray(r?.sheets)) {
        setSheets(normalizeSheets(r.sheets))
        setDicts(r.dicts || {})
        setGroups(Array.isArray(r.groups) ? r.groups : [])
        setAutomations(normalizeAutomations(r.automations))
        posRef.current = {}
      }
      setCheck(r?.check ?? (r?.error ? { error: r.error } : null))
      if (r?.error) {
        message.error(`生成失败:${String(r.error).split('\n')[0].slice(0, 200)}`)
      } else {
        message.success('ER 设计已生成')
        onGenerated?.('design')
      }
      await loadEr()
    } catch (e) {
      message.error(errMsg(e))
    } finally {
      setGenerating(false)
    }
  }

  async function save() {
    const autoErrs = validateAutomations(automations)
    if (autoErrs.length) {
      message.error(`自动化配置不合法:${autoErrs[0]}${autoErrs.length > 1 ? ` 等 ${autoErrs.length} 处` : ''}`)
      setCheck({ error: `自动化配置不合法:\n${autoErrs.join('\n')}` })
      return
    }
    setSaving(true)
    try {
      const res = await put<any>(`/api/projects/${projectId}/design`, {
        sheets,
        dicts,
        groups,
        automations,
      })
      setCheck(res?.check ?? (res?.error ? { error: res.error } : null))
      if (res?.error) message.error(`保存后校验未通过:${String(res.error).split('\n')[0].slice(0, 200)}`)
      else message.success('设计已保存')
      await loadEr()
    } catch (e) {
      message.error(errMsg(e))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div>
      <Card
        title={`ER 设计(${sheets.length} 张表 · ${automations.length} 条自动化)`}
        extra={
          <Space wrap>
            <Button
              type="primary"
              icon={<RobotOutlined />}
              loading={generating}
              disabled={!canWrite || !!gate}
              onClick={generate}
            >
              生成 ER 图
            </Button>
            <Button icon={<SaveOutlined />} loading={saving} disabled={!canWrite} onClick={save}>
              保存设计
            </Button>
            <Button icon={<ReloadOutlined />} loading={checking} onClick={runCheck}>
              重新校验
            </Button>
            <Button onClick={load}>刷新</Button>
          </Space>
        }
      >
        {gate ? (
          <Alert
            type="warning"
            showIcon
            style={{ marginBottom: 12 }}
            message="前置条件未满足"
            description={gate}
          />
        ) : null}
        {loading ? (
          <div style={{ textAlign: 'center', padding: 40 }}>
            <Typography.Text type="secondary">加载中...</Typography.Text>
          </div>
        ) : sheets.length ? (
          <div className="er-flow-wrap">
            <ReactFlow
              nodes={nodes}
              edges={flowEdges}
              nodeTypes={nodeTypes}
              onNodesChange={onNodesChange}
              onEdgesChange={onEdgesChange}
              onNodeDragStop={(_, n) => {
                posRef.current[n.id] = n.position
              }}
              fitView
              proOptions={{ hideAttribution: true }}
            >
              <Background />
              <Controls />
              <MiniMap pannable zoomable />
            </ReactFlow>
          </div>
        ) : (
          <Empty description="尚未生成 ER 设计">
            <Button
              type="primary"
              icon={<RobotOutlined />}
              loading={generating}
              disabled={!canWrite || !!gate}
              onClick={generate}
            >
              生成 ER 图
            </Button>
          </Empty>
        )}

        {check ? (
          <Card size="small" title="引擎校验结果" style={{ marginTop: 16 }}>
            {check.error ? (
              <Alert type="error" showIcon message="校验未通过" description={String(check.error)} />
            ) : (
              <>
                <Alert
                  type={check.warnings && check.warnings.length ? 'warning' : 'success'}
                  showIcon
                  message={`校验通过:${(check.sheets || []).length} 张表`}
                  description={
                    check.warnings && check.warnings.length ? (
                      <div>
                        {check.warnings.map((w: string, i: number) => (
                          <div key={i}>{w}</div>
                        ))}
                      </div>
                    ) : null
                  }
                />
                <Table
                  size="small"
                  rowKey="key"
                  style={{ marginTop: 12 }}
                  pagination={false}
                  dataSource={check.sheets || []}
                  columns={[
                    { title: '表', dataIndex: 'key' },
                    { title: '名称', dataIndex: 'title' },
                    { title: '字段数', dataIndex: 'fields', width: 80 },
                    { title: '规则', dataIndex: 'rules', width: 70 },
                    {
                      title: '子表',
                      width: 160,
                      render: (_: any, r: any) =>
                        (r.subtables || []).map((x: any) => x.key).join(', ') || '-',
                    },
                    { title: '分组', dataIndex: 'group', width: 120 },
                  ]}
                />
              </>
            )}
          </Card>
        ) : null}
      </Card>

      {sheets.length ? (
        <Tabs
          style={{ marginTop: 16 }}
          defaultActiveKey="sheets"
          items={[
            {
              key: 'sheets',
              label: `表单结构(${sheets.length})`,
              children: (
                <>
                  <div className="design-toolbar">
                    <Space>
                      <Button icon={<PlusOutlined />} disabled={!canWrite} onClick={addSheet}>
                        新增表
                      </Button>
                      <Typography.Text type="secondary">
                        提示:字段编码需字母开头、只含字母数字;关键字表被 query 关联时需先建。
                      </Typography.Text>
                    </Space>
                  </div>
          <Collapse
            accordion
            items={sheets.map((s, si) => ({
              key: s.key + '_' + si,
              label: (
                <Space>
                  <Tag color="blue">{s.key}</Tag>
                  <span>{s.title}</span>
                  <Typography.Text type="secondary">({s.controls.length} 字段)</Typography.Text>
                </Space>
              ),
              extra: canWrite ? (
                <Button
                  size="small"
                  type="link"
                  danger
                  icon={<DeleteOutlined />}
                  onClick={(ev) => {
                    ev.stopPropagation()
                    removeSheet(si)
                  }}
                >
                  删除表
                </Button>
              ) : null,
              children: (
                <div>
                  <div className="field-row">
                    <span style={{ width: 64 }}>表名称</span>
                    <Input
                      style={{ width: 200 }}
                      value={s.title}
                      disabled={!canWrite}
                      onChange={(e) => updateSheet(si, { title: e.target.value })}
                    />
                    <span style={{ width: 48 }}>表 key</span>
                    <Input
                      style={{ width: 160 }}
                      value={s.key}
                      disabled={!canWrite}
                      onChange={(e) => updateSheet(si, { key: e.target.value })}
                    />
                    <span style={{ width: 40 }}>分组</span>
                    <Input
                      style={{ width: 140 }}
                      value={s.group || ''}
                      disabled={!canWrite}
                      onChange={(e) => updateSheet(si, { group: e.target.value })}
                    />
                    <span>启用申请人</span>
                    <Switch
                      size="small"
                      checked={!!s.useOwner}
                      disabled={!canWrite}
                      onChange={(v) => updateSheet(si, { useOwner: v })}
                    />
                  </div>

                  <Typography.Text strong style={{ display: 'block', margin: '12px 0 6px' }}>
                    字段
                  </Typography.Text>
                  {s.controls.map((c, ci) => (
                    <div key={ci}>
                      <div className="field-row">
                        <Input
                          style={{ width: 160 }}
                          placeholder="字段名称"
                          value={c.label}
                          disabled={!canWrite}
                          onChange={(e) => updateControl(si, ci, { label: e.target.value })}
                        />
                        <Input
                          style={{ width: 140 }}
                          placeholder="字段编码"
                          value={c.key}
                          disabled={!canWrite}
                          onChange={(e) => updateControl(si, ci, { key: e.target.value })}
                        />
                        <Select
                          style={{ width: 150 }}
                          value={c.type}
                          disabled={!canWrite}
                          onChange={(v) =>
                            updateControl(si, ci, {
                              type: v,
                              ...(v === 'subtable' && !c.columns ? { columns: [] } : {}),
                            })
                          }
                          options={CONTROL_TYPES}
                        />
                        <span>必填</span>
                        <Switch
                          size="small"
                          checked={!!c.required}
                          disabled={!canWrite}
                          onChange={(v) => updateControl(si, ci, { required: v })}
                        />
                        {DICT_TYPES.includes(c.type) ? (
                          <Input
                            style={{ width: 140 }}
                            placeholder="字典名 dict"
                            value={c.dict}
                            disabled={!canWrite}
                            onChange={(e) => updateControl(si, ci, { dict: e.target.value })}
                          />
                        ) : null}
                        {c.type === 'query' ? (
                          <Input
                            style={{ width: 150 }}
                            placeholder="关联表 key (assoc)"
                            value={c.assoc}
                            disabled={!canWrite}
                            onChange={(e) => updateControl(si, ci, { assoc: e.target.value })}
                          />
                        ) : null}
                        {canWrite ? (
                          <Button
                            size="small"
                            danger
                            icon={<DeleteOutlined />}
                            onClick={() => removeControl(si, ci)}
                          />
                        ) : null}
                      </div>

                      {c.type === 'subtable' ? (
                        <div className="subtable-box">
                          {(c.columns || []).map((col, k) => (
                            <div className="field-row" key={k}>
                              <Input
                                size="small"
                                style={{ width: 140 }}
                                placeholder="列名称"
                                value={col.label}
                                disabled={!canWrite}
                                onChange={(e) => updateColumn(si, ci, k, { label: e.target.value })}
                              />
                              <Input
                                size="small"
                                style={{ width: 120 }}
                                placeholder="列编码"
                                value={col.key}
                                disabled={!canWrite}
                                onChange={(e) => updateColumn(si, ci, k, { key: e.target.value })}
                              />
                              <Select
                                size="small"
                                style={{ width: 130 }}
                                value={col.type}
                                disabled={!canWrite}
                                onChange={(v) => updateColumn(si, ci, k, { type: v })}
                                options={CONTROL_TYPES.filter((t) =>
                                  COLUMN_TYPES.includes(t.value),
                                )}
                              />
                              {canWrite ? (
                                <Button
                                  size="small"
                                  danger
                                  icon={<DeleteOutlined />}
                                  onClick={() => removeColumn(si, ci, k)}
                                />
                              ) : null}
                            </div>
                          ))}
                          {canWrite ? (
                            <Button
                              size="small"
                              type="dashed"
                              icon={<PlusOutlined />}
                              onClick={() => addColumn(si, ci)}
                            >
                              添加列
                            </Button>
                          ) : null}
                        </div>
                      ) : null}
                    </div>
                  ))}
                  {canWrite ? (
                    <Button size="small" type="dashed" icon={<PlusOutlined />} onClick={() => addControl(si)}>
                      添加字段
                    </Button>
                  ) : null}
                </div>
              ),
            }))}
                  />
                </>
              ),
            },
            {
              key: 'groups',
              label: `分组(${groups.length})`,
              children: (
                <GroupsEditor
                  groups={groups}
                  sheets={sheets}
                  canWrite={canWrite}
                  onChange={setGroups}
                />
              ),
            },
            {
              key: 'automations',
              label: `自动化(${automations.length})`,
              children: (
                <AutomationEditor
                  automations={automations}
                  sheets={sheets}
                  canWrite={canWrite}
                  onChange={setAutomations}
                />
              ),
            },
          ]}
        />
      ) : null}
    </div>
  )
}
