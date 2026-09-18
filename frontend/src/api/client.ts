import axios, { AxiosRequestConfig } from 'axios'

/**
 * 统一 HTTP 客户端。
 * - 会话在 httpOnly Cookie 里,所有请求带 Cookie(withCredentials)。
 * - baseURL 为空,开发期走 vite 的 /api 代理到 http://localhost:8000。
 * - 401 时通知应用清空登录态并跳转 /login。
 */
export const api = axios.create({
  baseURL: '',
  withCredentials: true,
  timeout: 180000,
})

export class ApiError extends Error {
  status: number
  constructor(message: string, status = 0) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

let unauthorizedHandler: (() => void) | null = null

export function setUnauthorizedHandler(fn: (() => void) | null) {
  unauthorizedHandler = fn
}

api.interceptors.response.use(
  (response) => response,
  (error) => {
    const status = error?.response?.status
    if (status === 401) {
      try {
        unauthorizedHandler?.()
      } catch {
        /* ignore */
      }
      if (typeof window !== 'undefined' && !window.location.hash.startsWith('#/login')) {
        window.location.hash = '#/login'
      }
    }
    return Promise.reject(error)
  },
)

function unwrap(payload: any): any {
  if (payload && typeof payload === 'object' && 'ok' in payload) {
    if (payload.ok === false) {
      throw new ApiError(payload.message || payload.error || '请求失败')
    }
    return payload.data
  }
  return payload
}

export async function get<T = any>(url: string, config?: AxiosRequestConfig): Promise<T> {
  const res = await api.get(url, config)
  return unwrap(res.data) as T
}

export async function post<T = any>(url: string, data?: any, config?: AxiosRequestConfig): Promise<T> {
  const res = await api.post(url, data, config)
  return unwrap(res.data) as T
}

export async function put<T = any>(url: string, data?: any, config?: AxiosRequestConfig): Promise<T> {
  const res = await api.put(url, data, config)
  return unwrap(res.data) as T
}

export async function patch<T = any>(url: string, data?: any, config?: AxiosRequestConfig): Promise<T> {
  const res = await api.patch(url, data, config)
  return unwrap(res.data) as T
}

export async function del<T = any>(url: string, config?: AxiosRequestConfig): Promise<T> {
  const res = await api.delete(url, config)
  return unwrap(res.data) as T
}

/** 从任意异常里提取可展示的错误消息。 */
export function errMsg(e: any): string {
  if (!e) return '请求失败'
  if (e instanceof ApiError) return e.message

  const data = e?.response?.data
  if (typeof data === 'string' && data) return data
  if (data && typeof data === 'object') {
    if (typeof data.message === 'string' && data.message) return data.message
    if (typeof data.detail === 'string' && data.detail) return data.detail
    if (Array.isArray(data.detail) && data.detail.length) {
      return data.detail.map((x: any) => x?.msg || JSON.stringify(x)).join('; ')
    }
    if (typeof data.error === 'string' && data.error) return data.error
  }
  if (e?.code === 'ECONNABORTED') return '请求超时,请稍后重试'
  return e?.message || '请求失败'
}

/* ------------------------------------------------------------------ 类型 */

export type Role = 'admin' | 'designer' | 'viewer' | string

export interface User {
  id: number
  email: string
  displayName: string
  role: Role
  active: boolean
  createdAt?: string
}

export interface Project {
  id: number
  slug: string
  title: string
  engineCode: string
  appCode: string
  status: string
  ownerId: number
  hasToken: boolean
  createdAt: string
  updatedAt: string
  canWrite?: boolean
  role?: string
}

export interface HealthInfo {
  ok: boolean
  provider?: string
  needsBootstrap?: boolean
  llm?: boolean
  knowledge?: boolean
  version?: string
}

export type DocKind = 'existing_system' | 'requirement' | 'meeting' | 'other'

export interface DocumentItem {
  id: number
  projectId?: number
  kind: string
  filename: string
  ext?: string
  size?: number
  summary?: string
  status?: string
  createdAt?: string
}

/** ER 设计里的单个控件,字段名严格对齐后端 h3service.design。 */
export interface Control {
  type: string
  key?: string
  label?: string
  required?: boolean
  readonly?: boolean
  hideWhen?: string
  uiNote?: string
  dict?: string
  options?: any[]
  defaults?: any[]
  default?: any
  assoc?: string
  columns?: Control[]
  [k: string]: any
}

export interface Sheet {
  key: string
  title: string
  nameSchema?: string
  useOwner?: boolean
  group?: string
  layout?: any
  controls: Control[]
}

/** 自动化(触发器)DSL,对齐 docs/schema_doc.md「自动化」章节。 */
export interface AutomationWhen {
  field: string
  value?: any
}

export interface AutomationSet {
  to: string
  from: string
}

export interface AutomationMatch {
  field: string
  ref?: string
  value?: any
}

export interface AutomationSub {
  table: string
  set: AutomationSet[]
}

export type AutomationDo = '新增' | '更新' | '删除'
export type AutomationTrigger = '生效' | '失效' | '生效或更新'

export interface AutomationAction {
  do: AutomationDo
  target: string
  state?: string
  isInsert?: boolean
  match?: AutomationMatch[]
  set?: AutomationSet[]
  owner?: boolean
  sub?: AutomationSub
}

export interface Automation {
  key: string
  title?: string
  form: string
  trigger: AutomationTrigger
  sortKey?: number
  names?: Record<string, string>
  when?: AutomationWhen[]
  actions: AutomationAction[]
}

export interface Design {
  sheets: Sheet[]
  dicts: Record<string, any[]>
  groups: any[]
  automations: Automation[]
}

export const AUTOMATION_TRIGGERS: { value: AutomationTrigger; label: string }[] = [
  { value: '生效', label: '生效' },
  { value: '失效', label: '失效' },
  { value: '生效或更新', label: '生效或更新' },
]

export const AUTOMATION_DOS: { value: AutomationDo; label: string }[] = [
  { value: '新增', label: '新增' },
  { value: '更新', label: '更新' },
  { value: '删除', label: '删除' },
]

export const AUTOMATION_STATES: { value: string; label: string }[] = [
  { value: '生效', label: '生效' },
  { value: '发起流程', label: '发起流程' },
]

/** 从 sheets 提取表/字段候选,供自动化编辑器的下拉使用。 */
export interface SheetFieldOption {
  value: string
  label: string
}

export interface SubtableOption {
  value: string
  label: string
  columns: SheetFieldOption[]
}

export interface SheetCatalog {
  sheets: { value: string; label: string }[]
  mainFields: Record<string, SheetFieldOption[]>
  subtables: Record<string, SubtableOption[]>
}

export function buildCatalog(sheets: Sheet[] | undefined | null): SheetCatalog {
  const list = Array.isArray(sheets) ? sheets : []
  const sheetOptions: { value: string; label: string }[] = []
  const mainFields: Record<string, SheetFieldOption[]> = {}
  const subtables: Record<string, SubtableOption[]> = {}

  for (const s of list) {
    if (!s?.key) continue
    sheetOptions.push({ value: s.key, label: s.title ? `${s.title}(${s.key})` : s.key })

    const fields: SheetFieldOption[] = []
    const subs: SubtableOption[] = []
    for (const c of s.controls || []) {
      if (!c?.key) continue
      const label = `${c.label || c.key}(${c.key})`
      if (c.type === 'subtable') {
        subs.push({
          value: c.key,
          label,
          columns: (c.columns || [])
            .filter((col) => !!col?.key)
            .map((col) => ({ value: col.key as string, label: `${col.label || col.key}(${col.key})` })),
        })
      } else {
        fields.push({ value: c.key, label })
      }
    }
    mainFields[s.key] = fields
    subtables[s.key] = subs
  }
  return { sheets: sheetOptions, mainFields, subtables }
}

export const SYSTEM_REFS: SheetFieldOption[] = [
  { value: '$ObjectId', label: '系统:$ObjectId' },
  { value: '$OwnerId', label: '系统:$OwnerId' },
  { value: '$OwnerDeptId', label: '系统:$OwnerDeptId' },
]

/** 默认 key 生成器:auto_1、auto_2 …避开已占用的 key。 */
export function nextAutomationKey(existing: { key?: string }[] | undefined): string {
  const used = new Set((existing || []).map((a) => a?.key).filter(Boolean))
  let n = (existing?.length || 0) + 1
  let key = `auto_${n}`
  while (used.has(key)) {
    n += 1
    key = `auto_${n}`
  }
  return key
}

/** 校验 automation 列表:key 非空且唯一、form 必填。返回错误文本数组(空=通过)。 */
export function validateAutomations(list: Automation[] | undefined): string[] {
  const errs: string[] = []
  const seen = new Set<string>()
  ;(list || []).forEach((a, i) => {
    const no = `自动化 #${i + 1}`
    const key = (a?.key || '').trim()
    if (!key) errs.push(`${no}:key 不能为空`)
    else if (seen.has(key)) errs.push(`${no}:key「${key}」重复`)
    else seen.add(key)
    if (!(a?.form || '').trim()) errs.push(`${no}:触发表单不能为空`)
  })
  return errs
}

export interface ErField {
  key: string
  label: string
  type: any
  required?: boolean
  readonly?: boolean
  assoc?: string
  isSubtable?: boolean
  columns?: { key: string; label: string }[]
}

export interface ErNodeData {
  id: string
  title: string
  group?: string
  useOwner?: boolean
  fields: ErField[]
}

export interface ErEdge {
  source: string
  target: string
  field?: string
  label?: string
  kind?: string
}

export interface ErGraph {
  project?: string
  nodes: ErNodeData[]
  edges: ErEdge[]
}

export interface DeploySheetResult {
  key: string
  created?: boolean
  code?: string
  detail?: string
  err?: string
}

export interface DeployAutomationResult {
  key: string
  created?: boolean
  objectId?: string
  err?: string
}

export interface DeployGroupResult {
  group: string
  code?: string
  created?: boolean
  detail?: string
}

export interface DeployMoveResult {
  table: string
  group: string
  ok?: boolean
  detail?: string
}

export interface DeployResult {
  project?: Project
  sheets?: DeploySheetResult[]
  groups?: DeployGroupResult[]
  moved?: DeployMoveResult[]
  automations?: DeployAutomationResult[]
  all_ok?: boolean
  error?: string
  groupsError?: string
}

export interface ProjectMember {
  userId: number
  role: string
  email?: string
  displayName?: string
}

export interface CredentialsStatus {
  configured: boolean
  appCode?: string
  hasToken?: boolean
  engineCode?: string
  tokenValid?: boolean
  tokenExpired?: boolean
}

/** 与后端 DSL 一致的控件类型清单。 */
export const CONTROL_TYPES: { value: string; label: string }[] = [
  { value: 'text', label: '单行文本' },
  { value: 'textarea', label: '多行文本' },
  { value: 'number', label: '数字' },
  { value: 'date', label: '日期' },
  { value: 'switch', label: '开关' },
  { value: 'radio', label: '单选' },
  { value: 'dropdown', label: '下拉' },
  { value: 'checkbox_list', label: '多选' },
  { value: 'member', label: '成员' },
  { value: 'department', label: '部门' },
  { value: 'query', label: '关联查询' },
  { value: 'seq_no', label: '流水号' },
  { value: 'image', label: '图片' },
  { value: 'attachment', label: '附件' },
  { value: 'location', label: '定位' },
  { value: 'address', label: '地址' },
  { value: 'formula', label: '公式' },
  { value: 'group_title', label: '分组标题' },
  { value: 'description', label: '说明文字' },
  { value: 'subtable', label: '子表' },
]

/** 子表列允许的控件类型。 */
export const COLUMN_TYPES = [
  'text',
  'textarea',
  'number',
  'date',
  'switch',
  'radio',
  'dropdown',
  'checkbox_list',
  'attachment',
  'image',
]

export const DOC_KINDS: { value: DocKind; label: string }[] = [
  { value: 'requirement', label: '需求文档' },
  { value: 'existing_system', label: '现有系统资料' },
  { value: 'meeting', label: '会议纪要' },
  { value: 'other', label: '其他' },
]

export const STATUS_META: Record<string, { color: string; text: string }> = {
  draft: { color: 'default', text: '草稿' },
  planned: { color: 'blue', text: '已出方案' },
  flowcharted: { color: 'cyan', text: '已出流程图' },
  designed: { color: 'geekblue', text: '已设计' },
  deployed: { color: 'green', text: '已生成应用' },
  failed: { color: 'red', text: '失败' },
}
