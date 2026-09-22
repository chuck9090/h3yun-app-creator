import {
  AutoComplete,
  Button,
  Collapse,
  Empty,
  Input,
  InputNumber,
  Select,
  Space,
  Switch,
  Tag,
  Typography,
} from 'antd'
import { DeleteOutlined, PlusOutlined } from '@ant-design/icons'
import {
  AUTOMATION_DOS,
  AUTOMATION_STATES,
  AUTOMATION_TRIGGERS,
  Automation,
  AutomationAction,
  AutomationMatch,
  AutomationSet,
  AutomationWhen,
  buildCatalog,
  nextAutomationKey,
  SYSTEM_REFS,
  Sheet,
  SheetFieldOption,
} from '../api/client'

function mergeOptions(...groups: SheetFieldOption[][]): SheetFieldOption[] {
  const seen = new Set<string>()
  const out: SheetFieldOption[] = []
  for (const g of groups) {
    for (const o of g || []) {
      if (!o?.value || seen.has(o.value)) continue
      seen.add(o.value)
      out.push(o)
    }
  }
  return out
}

function refOptions(catalog: ReturnType<typeof buildCatalog>, formKey: string): SheetFieldOption[] {
  const subs = (catalog.subtables[formKey] || []).flatMap((sub) =>
    sub.columns.map((col) => ({
      value: `${sub.value}.${col.value}`,
      label: `${sub.label}→${col.label}`,
    })),
  )
  return mergeOptions(catalog.mainFields[formKey] || [], subs, SYSTEM_REFS)
}

export default function AutomationEditor({
  automations,
  sheets,
  canWrite,
  onChange,
}: {
  automations: Automation[]
  sheets: Sheet[]
  canWrite: boolean
  onChange: (list: Automation[]) => void
}) {
  const catalog = buildCatalog(sheets)
  const list = Array.isArray(automations) ? automations : []

  function setList(next: Automation[]) {
    onChange(next)
  }

  function patchAutomation(i: number, patch: Partial<Automation>) {
    setList(list.map((a, idx) => (idx === i ? { ...a, ...patch } : a)))
  }

  function addAutomation() {
    setList([
      ...list,
      {
        key: nextAutomationKey(list),
        title: '新自动化',
        form: catalog.sheets[0]?.value || '',
        trigger: '生效',
        sortKey: list.length + 1,
        when: [],
        actions: [{ do: '新增', target: catalog.sheets[0]?.value || '', set: [] }],
      },
    ])
  }

  function removeAutomation(i: number) {
    setList(list.filter((_, idx) => idx !== i))
  }

  function patchAction(ai: number, pi: number, patch: Partial<AutomationAction>) {
    patchAutomation(ai, {
      actions: list[ai].actions.map((ac, idx) => (idx === pi ? { ...ac, ...patch } : ac)),
    })
  }

  function addAction(ai: number) {
    patchAutomation(ai, {
      actions: [
        ...list[ai].actions,
        { do: '新增', target: catalog.sheets[0]?.value || '', set: [] },
      ],
    })
  }

  function removeAction(ai: number, pi: number) {
    patchAutomation(ai, { actions: list[ai].actions.filter((_, idx) => idx !== pi) })
  }

  function patchWhen(ai: number, wi: number, patch: Partial<AutomationWhen>) {
    const when = (list[ai].when || []).map((w, idx) => (idx === wi ? { ...w, ...patch } : w))
    patchAutomation(ai, { when })
  }

  function addWhen(ai: number) {
    patchAutomation(ai, { when: [...(list[ai].when || []), { field: '', value: '' }] })
  }

  function removeWhen(ai: number, wi: number) {
    patchAutomation(ai, { when: (list[ai].when || []).filter((_, idx) => idx !== wi) })
  }

  function patchMatch(ai: number, pi: number, mi: number, patch: Partial<AutomationMatch>) {
    const ac = list[ai].actions[pi]
    patchAction(ai, pi, {
      match: (ac.match || []).map((m, idx) => (idx === mi ? { ...m, ...patch } : m)),
    })
  }

  function addMatch(ai: number, pi: number) {
    const ac = list[ai].actions[pi]
    patchAction(ai, pi, { match: [...(ac.match || []), { field: '' }] })
  }

  function removeMatch(ai: number, pi: number, mi: number) {
    const ac = list[ai].actions[pi]
    patchAction(ai, pi, { match: (ac.match || []).filter((_, idx) => idx !== mi) })
  }

  function patchSet(ai: number, pi: number, si: number, patch: Partial<AutomationSet>) {
    const ac = list[ai].actions[pi]
    patchAction(ai, pi, {
      set: (ac.set || []).map((s, idx) => (idx === si ? { ...s, ...patch } : s)),
    })
  }

  function addSet(ai: number, pi: number) {
    const ac = list[ai].actions[pi]
    patchAction(ai, pi, { set: [...(ac.set || []), { to: '', from: '' }] })
  }

  function removeSet(ai: number, pi: number, si: number) {
    const ac = list[ai].actions[pi]
    patchAction(ai, pi, { set: (ac.set || []).filter((_, idx) => idx !== si) })
  }

  function toggleSub(ai: number, pi: number, enabled: boolean) {
    const ac = list[ai].actions[pi]
    if (!enabled) {
      patchAction(ai, pi, { sub: undefined })
      return
    }
    const subs = catalog.subtables[ac.target] || []
    patchAction(ai, pi, { sub: { table: subs[0]?.value || '', set: [] } })
  }

  function patchSub(ai: number, pi: number, patch: Partial<NonNullable<AutomationAction['sub']>>) {
    const ac = list[ai].actions[pi]
    const sub = ac.sub || { table: '', set: [] }
    patchAction(ai, pi, { sub: { ...sub, ...patch } })
  }

  function patchSubSet(ai: number, pi: number, si: number, patch: Partial<AutomationSet>) {
    const ac = list[ai].actions[pi]
    const sub = ac.sub || { table: '', set: [] }
    patchSub(ai, pi, {
      set: sub.set.map((s, idx) => (idx === si ? { ...s, ...patch } : s)),
    })
  }

  function addSubSet(ai: number, pi: number) {
    const ac = list[ai].actions[pi]
    const sub = ac.sub || { table: '', set: [] }
    patchSub(ai, pi, { set: [...sub.set, { to: '', from: '' }] })
  }

  function removeSubSet(ai: number, pi: number, si: number) {
    const ac = list[ai].actions[pi]
    const sub = ac.sub || { table: '', set: [] }
    patchSub(ai, pi, { set: sub.set.filter((_, idx) => idx !== si) })
  }

  const items = list.map((a, ai) => {
    const formRefs = refOptions(catalog, a.form)
    return {
      key: `${a.key || 'auto'}_${ai}`,
      label: (
        <Space>
          <Tag color={a.form ? 'geekblue' : 'red'}>{a.key || '(未命名)'}</Tag>
          <span>{a.title || '未命名自动化'}</span>
          <Typography.Text type="secondary">
            {a.form || '未选表'} · {a.trigger}
          </Typography.Text>
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
            removeAutomation(ai)
          }}
        >
          删除
        </Button>
      ) : null,
      children: (
        <div>
          <div className="field-row">
            <span style={{ width: 48 }}>key</span>
            <Input
              style={{ width: 150 }}
              value={a.key}
              disabled={!canWrite}
              placeholder="a1"
              onChange={(e) => patchAutomation(ai, { key: e.target.value })}
            />
            <span style={{ width: 48 }}>标题</span>
            <Input
              style={{ width: 240 }}
              value={a.title}
              disabled={!canWrite}
              onChange={(e) => patchAutomation(ai, { title: e.target.value })}
            />
            <span style={{ width: 64 }}>触发表单</span>
            <Select
              style={{ width: 180 }}
              value={a.form || undefined}
              disabled={!canWrite}
              placeholder="选择表"
              options={catalog.sheets}
              onChange={(v) => patchAutomation(ai, { form: v })}
            />
            <span style={{ width: 48 }}>触发</span>
            <Select
              style={{ width: 130 }}
              value={a.trigger}
              disabled={!canWrite}
              options={AUTOMATION_TRIGGERS}
              onChange={(v) => patchAutomation(ai, { trigger: v })}
            />
            <span style={{ width: 60 }}>排序号</span>
            <InputNumber
              style={{ width: 90 }}
              value={a.sortKey}
              disabled={!canWrite}
              onChange={(v) => patchAutomation(ai, { sortKey: v ?? undefined })}
            />
          </div>

          {/* when 条件 */}
          <Typography.Text strong style={{ display: 'block', margin: '12px 0 6px' }}>
            触发条件 when(外层为或,组内为且)
          </Typography.Text>
          {(a.when || []).map((w, wi) => (
            <div className="field-row" key={wi}>
              <span style={{ width: 48 }}>字段</span>
              <Select
                style={{ width: 220 }}
                value={w.field || undefined}
                disabled={!canWrite}
                placeholder="触发表字段"
                options={catalog.mainFields[a.form] || []}
                onChange={(v) => patchWhen(ai, wi, { field: v })}
              />
              <span style={{ width: 40 }}>值</span>
              <Input
                style={{ width: 200 }}
                value={w.value == null ? '' : String(w.value)}
                disabled={!canWrite}
                placeholder="比较值"
                onChange={(e) => patchWhen(ai, wi, { value: e.target.value })}
              />
              {canWrite ? (
                <Button size="small" danger icon={<DeleteOutlined />} onClick={() => removeWhen(ai, wi)} />
              ) : null}
            </div>
          ))}
          {canWrite ? (
            <Button size="small" type="dashed" icon={<PlusOutlined />} onClick={() => addWhen(ai)}>
              添加条件
            </Button>
          ) : null}

          {/* actions 动作 */}
          <Typography.Text strong style={{ display: 'block', margin: '12px 0 6px' }}>
            动作 actions
          </Typography.Text>
          {(a.actions || []).map((ac, pi) => {
            const subs = catalog.subtables[ac.target] || []
            const targetFields = catalog.mainFields[ac.target] || []
            const subColumns = subs.find((s) => s.value === ac.sub?.table)?.columns || []
            return (
              <div className="automation-action" key={pi}>
                <div className="field-row">
                  <span style={{ width: 48 }}>动作</span>
                  <Select
                    style={{ width: 100 }}
                    value={ac.do}
                    disabled={!canWrite}
                    options={AUTOMATION_DOS}
                    onChange={(v) => patchAction(ai, pi, { do: v })}
                  />
                  <span style={{ width: 48 }}>目标表</span>
                  <Select
                    style={{ width: 180 }}
                    value={ac.target || undefined}
                    disabled={!canWrite}
                    placeholder="选择表"
                    options={catalog.sheets}
                    onChange={(v) => patchAction(ai, pi, { target: v })}
                  />
                  {ac.do !== '删除' ? (
                    <>
                      <span style={{ width: 48 }}>状态</span>
                      <Select
                        style={{ width: 120 }}
                        value={ac.state || undefined}
                        disabled={!canWrite}
                        allowClear
                        placeholder="生效"
                        options={AUTOMATION_STATES}
                        onChange={(v) => patchAction(ai, pi, { state: v || undefined })}
                      />
                    </>
                  ) : null}
                  {ac.do === '更新' ? (
                    <>
                      <span>匹配不到则新增</span>
                      <Switch
                        size="small"
                        checked={ac.isInsert !== false}
                        disabled={!canWrite}
                        onChange={(v) => patchAction(ai, pi, { isInsert: v })}
                      />
                    </>
                  ) : null}
                  {ac.do !== '删除' ? (
                    <>
                      <span>补拥有者</span>
                      <Switch
                        size="small"
                        checked={ac.owner !== false}
                        disabled={!canWrite}
                        onChange={(v) => patchAction(ai, pi, { owner: v })}
                      />
                    </>
                  ) : null}
                  {canWrite ? (
                    <Button size="small" danger icon={<DeleteOutlined />} onClick={() => removeAction(ai, pi)} />
                  ) : null}
                </div>

                {/* match */}
                {ac.do !== '新增' ? (
                  <div className="automation-sub">
                    <Typography.Text type="secondary">
                      match 定位目标记录(更新/删除必填)
                    </Typography.Text>
                    {(ac.match || []).map((m, mi) => (
                      <div className="field-row" key={mi}>
                        <span style={{ width: 48 }}>目标</span>
                        <Select
                          style={{ width: 200 }}
                          value={m.field || undefined}
                          disabled={!canWrite}
                          placeholder="目标表字段"
                          options={targetFields}
                          onChange={(v) => patchMatch(ai, pi, mi, { field: v })}
                        />
                        <span style={{ width: 84 }}>ref 源字段</span>
                        <AutoComplete
                          style={{ width: 200 }}
                          value={m.ref}
                          disabled={!canWrite}
                          options={formRefs}
                          placeholder="如 $ObjectId 或 t1"
                          onChange={(v) => patchMatch(ai, pi, mi, { ref: v })}
                          filterOption={(input, opt) =>
                            String(opt?.value || '').toLowerCase().includes(input.toLowerCase()) ||
                            String(opt?.label || '').toLowerCase().includes(input.toLowerCase())
                          }
                        />
                        <span style={{ width: 76 }}>value 常量</span>
                        <Input
                          style={{ width: 160 }}
                          value={m.value == null ? '' : String(m.value)}
                          disabled={!canWrite}
                          placeholder="二选一"
                          onChange={(e) => patchMatch(ai, pi, mi, { value: e.target.value })}
                        />
                        {canWrite ? (
                          <Button size="small" danger icon={<DeleteOutlined />} onClick={() => removeMatch(ai, pi, mi)} />
                        ) : null}
                      </div>
                    ))}
                    {canWrite ? (
                      <Button size="small" type="dashed" icon={<PlusOutlined />} onClick={() => addMatch(ai, pi)}>
                        添加 match
                      </Button>
                    ) : null}
                  </div>
                ) : null}

                {/* set */}
                {ac.do !== '删除' ? (
                  <div className="automation-sub">
                    <Typography.Text type="secondary">set 源字段 → 目标字段</Typography.Text>
                    {(ac.set || []).map((s, si) => (
                      <div className="field-row" key={si}>
                        <span style={{ width: 48 }}>目标</span>
                        <Select
                          style={{ width: 200 }}
                          value={s.to || undefined}
                          disabled={!canWrite}
                          placeholder="目标表字段"
                          options={targetFields}
                          onChange={(v) => patchSet(ai, pi, si, { to: v })}
                        />
                        <span style={{ width: 72 }}>源字段</span>
                        <AutoComplete
                          style={{ width: 220 }}
                          value={s.from}
                          disabled={!canWrite}
                          options={formRefs}
                          placeholder="触发表字段 / $ObjectId"
                          onChange={(v) => patchSet(ai, pi, si, { from: v })}
                          filterOption={(input, opt) =>
                            String(opt?.value || '').toLowerCase().includes(input.toLowerCase()) ||
                            String(opt?.label || '').toLowerCase().includes(input.toLowerCase())
                          }
                        />
                        {canWrite ? (
                          <Button size="small" danger icon={<DeleteOutlined />} onClick={() => removeSet(ai, pi, si)} />
                        ) : null}
                      </div>
                    ))}
                    {canWrite ? (
                      <Button size="small" type="dashed" icon={<PlusOutlined />} onClick={() => addSet(ai, pi)}>
                        添加 set
                      </Button>
                    ) : null}
                  </div>
                ) : null}

                {/* sub */}
                {ac.do !== '删除' ? (
                  <div className="automation-sub">
                    <Space size="small">
                      <Switch
                        size="small"
                        checked={!!ac.sub}
                        disabled={!canWrite}
                        onChange={(v) => toggleSub(ai, pi, v)}
                      />
                      <Typography.Text type="secondary">写入目标表的子表 sub</Typography.Text>
                    </Space>
                    {ac.sub ? (
                      <div style={{ marginTop: 6 }}>
                        <div className="field-row">
                          <span style={{ width: 60 }}>目标子表</span>
                          <Select
                            style={{ width: 200 }}
                            value={ac.sub.table || undefined}
                            disabled={!canWrite}
                            placeholder="选择子表"
                            options={subs.map((s) => ({ value: s.value, label: s.label }))}
                            onChange={(v) => patchSub(ai, pi, { table: v })}
                          />
                        </div>
                        {(ac.sub.set || []).map((s, si) => (
                          <div className="field-row" key={si}>
                            <span style={{ width: 60 }}>目标列</span>
                            <Select
                              style={{ width: 200 }}
                              value={s.to || undefined}
                              disabled={!canWrite}
                              placeholder="目标子表列"
                              options={subColumns}
                              onChange={(v) => patchSubSet(ai, pi, si, { to: v })}
                            />
                            <span style={{ width: 72 }}>源字段</span>
                            <AutoComplete
                              style={{ width: 220 }}
                              value={s.from}
                              disabled={!canWrite}
                              options={formRefs}
                              placeholder="触发表字段 / sub1.c1"
                              onChange={(v) => patchSubSet(ai, pi, si, { from: v })}
                              filterOption={(input, opt) =>
                                String(opt?.value || '').toLowerCase().includes(input.toLowerCase()) ||
                                String(opt?.label || '').toLowerCase().includes(input.toLowerCase())
                              }
                            />
                            {canWrite ? (
                              <Button
                                size="small"
                                danger
                                icon={<DeleteOutlined />}
                                onClick={() => removeSubSet(ai, pi, si)}
                              />
                            ) : null}
                          </div>
                        ))}
                        {canWrite ? (
                          <Button size="small" type="dashed" icon={<PlusOutlined />} onClick={() => addSubSet(ai, pi)}>
                            添加子表映射
                          </Button>
                        ) : null}
                      </div>
                    ) : null}
                  </div>
                ) : null}
              </div>
            )
          })}
          {canWrite ? (
            <Button size="small" type="dashed" icon={<PlusOutlined />} onClick={() => addAction(ai)}>
              添加动作
            </Button>
          ) : null}
        </div>
      ),
    }
  })

  return (
    <div>
      <Space style={{ marginBottom: 12 }}>
        {canWrite ? (
          <Button icon={<PlusOutlined />} onClick={addAutomation}>
            新增自动化
          </Button>
        ) : null}
        <Typography.Text type="secondary">
          共 {list.length} 条;key 必须非空且唯一,保存时会校验。
        </Typography.Text>
      </Space>
      {list.length ? (
        <Collapse items={items} />
      ) : (
        <Empty description="暂无自动化配置" />
      )}
    </div>
  )
}
