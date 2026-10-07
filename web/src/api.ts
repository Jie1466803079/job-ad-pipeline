// Types for the intake-api review routes, and one fetch helper. The shapes mirror
// api/jobpipe/review.py. Quote spans count Unicode code points, not UTF-16 units.

export const TABS = ['review', 'tracked', 'ineligible', 'applied', 'closed', 'skipped', 'dismissed'] as const
export type Tab = (typeof TABS)[number]

export type Decision = 'approve' | 'dismiss' | 'override_ineligible'
export type ApplicationStatus = 'tracked' | 'applied' | 'interview' | 'offer' | 'rejected'
export type FieldName =
  | 'work_rights'
  | 'security_clearance'
  | 'closing_date'
  | 'locations'
  | 'work_mode'
  | 'seniority'
  | 'employment_type'
  | 'salary'
export type Span = [start: number, end: number]

export interface QueueItem {
  id: number
  company: string
  title: string
  url: string
  status: string
  closed: boolean
  locations: string[]
  work_rights: string | null
  closing_date: string | null
  fit: { matched: number; total: number } | null
  reasons: string[]
  skip_reason: string | null
}

export interface QueuePage {
  tab: Tab
  total: number
  items: QueueItem[]
}

export interface Check {
  name: 'quote_found' | 'matches_quote' | 'agrees_with_board'
  status: 'pass' | 'fail' | 'na'
  reason: string
}

export interface Salary {
  stated: boolean
  min: number
  max: number
  currency: string
  period: string
}

interface FieldCommon {
  quote: string
  span: Span | null
  checks: Check[]
  edited: boolean
  options: string[] | null
}

export type FieldView =
  | (FieldCommon & { name: 'locations'; value: string[]; extracted: string[] })
  | (FieldCommon & { name: 'salary'; value: Salary; extracted: Salary })
  | (FieldCommon & { name: Exclude<FieldName, 'locations' | 'salary'>; value: string; extracted: string })

export interface Skill {
  skill: string
  quote: string
  verified: boolean
  span: Span | null
}

export type HistoryEvent =
  | { kind: 'extraction'; at: string; model: string; route: string; failed: boolean }
  | {
      kind: 'review'
      at: string
      username: string
      action: 'edit' | 'set_status' | Decision
      fields: FieldName[]
      from_status: string | null
      to_status: string | null
    }

export interface PostingDetail {
  id: number
  company: string
  title: string
  url: string
  status: string
  closing_date: string | null
  closed_at: string | null
  skip_reason: string | null
  text: string | null
  text_deleted_at: string | null
  extraction: { model: string; route: string; reasons: string[]; failed: boolean } | null
  fields: FieldView[]
  skills: { required: Skill[]; nice_to_have: Skill[] }
  fit: { matched: string[]; missing: string[]; total: number; summary: string } | null
  history: HistoryEvent[]
  actions: { decisions: Decision[]; statuses: ApplicationStatus[]; can_edit: boolean }
}

export interface Stats {
  tabs: Record<Tab, number>
  today: {
    fetched: number
    created: number
    skipped: number
    tracked: number
    review: number
    ineligible: number
    closed: number
    failed: number
  }
  month: { extracted: number; auto_routed: number; llm_cost_usd: number }
}

export type FieldEdit = Partial<Record<FieldName, string | string[] | Salary>>

export class ApiError extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

let onUnauthorized = (): void => {}

/** Called when a request gets 401 because the session has ended. */
export function setUnauthorizedHandler(handler: () => void): void {
  onUnauthorized = handler
}

/** FastAPI answers {"detail": "..."}, or {"detail": [{"msg": "..."}, ...]} for invalid input. */
export function detailText(data: unknown, status: number): string {
  if (typeof data === 'object' && data !== null && 'detail' in data) {
    const detail = data.detail
    if (typeof detail === 'string') return detail
    if (Array.isArray(detail)) {
      return detail
        .map((item: unknown) =>
          typeof item === 'object' && item !== null && 'msg' in item ? String(item.msg) : 'invalid value',
        )
        .join('; ')
    }
  }
  return `The request failed (${status}).`
}

export function messageOf(reason: unknown): string {
  return reason instanceof Error ? reason.message : String(reason)
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const response = await fetch(path, {
    method,
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (response.status === 401 && !path.startsWith('/auth/')) onUnauthorized()
  if (!response.ok) {
    const data: unknown = await response.json().catch(() => null)
    throw new ApiError(response.status, detailText(data, response.status))
  }
  return (response.status === 204 ? undefined : await response.json()) as T
}

export const api = {
  me: () => request<{ username: string }>('GET', '/auth/me'),
  login: (username: string, password: string) =>
    request<{ username: string }>('POST', '/auth/login', { username, password }),
  logout: () => request<void>('POST', '/auth/logout'),
  queue: (tab: Tab) => request<QueuePage>('GET', `/api/postings?tab=${tab}`),
  posting: (id: number) => request<PostingDetail>('GET', `/api/postings/${id}`),
  correct: (id: number, edit: FieldEdit) => request<PostingDetail>('PATCH', `/api/postings/${id}/fields`, edit),
  decide: (id: number, decision: Decision) =>
    request<PostingDetail>('POST', `/api/postings/${id}/decision`, { decision }),
  setStatus: (id: number, status: ApplicationStatus) =>
    request<PostingDetail>('PATCH', `/api/postings/${id}/status`, { status }),
  stats: () => request<Stats>('GET', '/api/stats'),
}
