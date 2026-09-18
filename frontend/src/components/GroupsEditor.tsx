import { useMemo, useState } from 'react'
import { App as AntApp, Button, Card, Empty, Input, Space, Tag, Typography } from 'antd'
import { ArrowDownOutlined, ArrowUpOutlined, DeleteOutlined, PlusOutlined } from '@ant-design/icons'
import type { Sheet } from '../api/client'

/**
 * 应用菜单分组的**顺序**编辑(部署时会按此顺序建分组并把表单移入)。
 * 分组名本身来自各表单的 `group` 字段;此处维护的是分组展示顺序与显式分组清单。
 */
export default function GroupsEditor({
  groups,
  sheets,
  canWrite,
  onChange,
}: {
  groups: any[]
  sheets: Sheet[]
  canWrite: boolean
  onChange: (g: any[]) => void
}) {
  const { message } = AntApp.useApp()
  const [draft, setDraft] = useState('')

  // 各表单上实际用到的分组名 → 对应表数量
  const used = useMemo(() => {
    const m: Record<string, number> = {}
    for (const s of sheets || []) {
      const g = (s.group || '').trim()
      if (g) m[g] = (m[g] || 0) + 1
    }
    return m
  }, [sheets])

  const list: string[] = useMemo(() => {
    const names = (groups || [])
      .map((g) => (typeof g === 'string' ? g : g?.name))
      .filter(Boolean)
    const merged = [...names]
    for (const g of Object.keys(used)) if (!merged.includes(g)) merged.push(g)
    return merged
  }, [groups, used])

  function commit(next: string[]) {
    onChange(next.map((name) => ({ name })))
  }
  function move(i: number, dir: -1 | 1) {
    const j = i + dir
    if (j < 0 || j >= list.length) return
    const next = [...list]
    ;[next[i], next[j]] = [next[j], next[i]]
    commit(next)
  }
  function remove(name: string) {
    if (used[name]) {
      message.warning(`分组「${name}」仍被 ${used[name]} 张表单使用,请先修改这些表单的分组`)
      return
    }
    commit(list.filter((x) => x !== name))
  }
  function add() {
    const name = draft.trim()
    if (!name) return
    if (list.includes(name)) {
      message.info('分组已存在')
      return
    }
    commit([...list, name])
    setDraft('')
  }

  return (
    <Card size="small" title="应用菜单分组(顺序 = 建组与菜单展示顺序)">
      <Typography.Paragraph type="secondary">
        分组名来自各表单「分组」字段;这里可调整**顺序**、或补充尚未被引用的分组名。
        生成应用时会按此顺序创建分组,并把表单移入对应分组(幂等,可重复执行)。
      </Typography.Paragraph>
      <Space style={{ marginBottom: 12 }}>
        <Input
          style={{ width: 200 }}
          placeholder="新分组名"
          value={draft}
          disabled={!canWrite}
          onChange={(e) => setDraft(e.target.value)}
          onPressEnter={add}
        />
        <Button icon={<PlusOutlined />} disabled={!canWrite} onClick={add}>
          添加分组
        </Button>
      </Space>
      {list.length ? (
        <div>
          {list.map((name, i) => (
            <div className="field-row" key={name}>
              <span style={{ width: 200 }}>{name}</span>
              <Tag color={used[name] ? 'blue' : 'default'}>
                {used[name] ? `${used[name]} 张表单` : '未引用'}
              </Tag>
              <Button
                size="small"
                icon={<ArrowUpOutlined />}
                disabled={!canWrite || i === 0}
                onClick={() => move(i, -1)}
              />
              <Button
                size="small"
                icon={<ArrowDownOutlined />}
                disabled={!canWrite || i === list.length - 1}
                onClick={() => move(i, 1)}
              />
              <Button
                size="small"
                danger
                icon={<DeleteOutlined />}
                disabled={!canWrite}
                onClick={() => remove(name)}
              />
            </div>
          ))}
        </div>
      ) : (
        <Empty description="暂无分组:在各表单填写「分组」字段后,这里会出现" />
      )}
    </Card>
  )
}
