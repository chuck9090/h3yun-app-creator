import { memo } from 'react'
import { Handle, Position, type NodeProps } from '@xyflow/react'
import type { Control } from '../api/client'

interface ErNodePayload {
  title: string
  key?: string
  fields?: Control[]
  [k: string]: unknown
}

function ErNodeInner({ data, selected }: NodeProps) {
  const d = (data || {}) as ErNodePayload
  const fields = d.fields || []
  return (
    <div className="er-node" style={selected ? { borderColor: '#1677ff' } : undefined}>
      <div className="er-node-title">
        <span>{d.title || d.key || '未命名'}</span>
        {d.key ? <span className="er-node-key">{d.key}</span> : null}
      </div>
      <div className="er-node-body">
        {fields.length ? (
          fields.map((f, i) => (
            <div className="er-node-field" key={`${f.key || 'f'}${i}`}>
              <span className="er-field-label" title={f.label || f.key}>
                {f.label || f.key || '(未命名)'}
              </span>
              <span className="er-field-type">{f.type}</span>
            </div>
          ))
        ) : (
          <div className="er-node-empty">暂无字段</div>
        )}
      </div>
      <Handle type="target" position={Position.Left} />
      <Handle type="source" position={Position.Right} />
    </div>
  )
}

export default memo(ErNodeInner)
