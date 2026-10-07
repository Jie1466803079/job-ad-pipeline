// Labels and plain-text versions of values, for display only.

import type { Check, Decision, FieldName, FieldView, HistoryEvent, Salary, Stats, Tab } from './api.ts'

export const TAB_LABELS: Record<Tab, string> = {
  review: 'Review',
  tracked: 'Tracked',
  ineligible: 'Not eligible',
  applied: 'Applied',
  closed: 'Closed',
  skipped: 'Skipped',
  dismissed: 'Dismissed',
}

export const FIELD_LABELS: Record<FieldName, string> = {
  work_rights: 'Work rights',
  security_clearance: 'Security clearance',
  closing_date: 'Closing date',
  locations: 'Locations',
  work_mode: 'Work mode',
  seniority: 'Seniority',
  employment_type: 'Employment type',
  salary: 'Salary',
}

const CHECK_LABELS: Record<Check['name'], string> = {
  quote_found: 'Quote found in the ad',
  matches_quote: 'Value matches the quote',
  agrees_with_board: 'Agrees with the job board',
}

const DECISIONS_DONE: Record<Decision, string> = {
  approve: 'approved it',
  dismiss: 'dismissed it',
  override_ineligible: 'tracked it despite Not eligible',
}

const UPPER_CASE = new Set(['pr', 'nv1', 'nv2', 'pv'])
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

/** "citizen_or_pr" becomes "citizen or PR". */
export function valueLabel(value: string): string {
  return value
    .split('_')
    .map((word) => (UPPER_CASE.has(word) ? word.toUpperCase() : word))
    .join(' ')
}

/** "2026-10-31" becomes "31 Oct 2026". */
export function dateLabel(value: string | null): string {
  if (!value || value === 'not_stated') return 'not stated'
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value)
  return match ? `${Number(match[3])} ${MONTHS[Number(match[2]) - 1]} ${match[1]}` : value
}

export function salaryLabel(salary: Salary): string {
  if (!salary.stated) return 'not stated'
  const amount = (value: number) => value.toLocaleString('en-AU')
  const range = salary.min === salary.max ? amount(salary.min) : `${amount(salary.min)} to ${amount(salary.max)}`
  return `${salary.currency} ${range} per ${salary.period}`.trim()
}

/** A field's current value, or the model's value with which = 'extracted'. */
export function fieldValueLabel(field: FieldView, which: 'value' | 'extracted' = 'value'): string {
  switch (field.name) {
    case 'locations': {
      const places = field[which]
      return places.length > 0 ? places.join('; ') : 'not stated'
    }
    case 'salary':
      return salaryLabel(field[which])
    case 'closing_date':
      return dateLabel(field[which])
    default:
      return valueLabel(field[which])
  }
}

export function checkLabel(check: Check): string {
  const result = check.status === 'pass' ? 'yes' : 'no'
  return `${CHECK_LABELS[check.name]}: ${result}${check.reason ? ` (${check.reason})` : ''}`
}

export function decisionLabel(decision: Decision, status: string): string {
  if (decision === 'dismiss') return 'Dismiss'
  if (decision === 'override_ineligible') return 'Track anyway'
  if (status === 'dismissed') return 'Restore'
  return status === 'skipped' ? 'Track anyway' : 'Approve'
}

export function historyLabel(event: HistoryEvent): string {
  if (event.kind === 'extraction') {
    return event.failed
      ? `Extraction by ${event.model} failed`
      : `Extracted by ${event.model} and routed to ${valueLabel(event.route)}`
  }
  if (event.action === 'edit') {
    return `${event.username} corrected ${event.fields.map((name) => FIELD_LABELS[name]).join(', ')}`
  }
  if (event.action === 'set_status') {
    return `${event.username} set the status to ${valueLabel(event.to_status ?? '')}`
  }
  return `${event.username} ${DECISIONS_DONE[event.action]}`
}

export function timeLabel(iso: string): string {
  return new Date(iso).toLocaleString('en-AU', {
    timeZone: 'Australia/Sydney',
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  })
}

export function statsLine(stats: Stats): string {
  const { today, month } = stats
  const share =
    month.extracted > 0
      ? `${Math.round((100 * month.auto_routed) / month.extracted)}% routed without review`
      : 'nothing extracted yet'
  return (
    `Today: ${today.fetched} fetched, ${today.created} new, ${today.tracked} tracked, ${today.review} to review. ` +
    `This month: US$${month.llm_cost_usd.toFixed(2)} of LLM calls, ${share}.`
  )
}

/** Only https links are made clickable. Anything else, such as a javascript: link, is dropped. */
export function safeUrl(url: string): string | undefined {
  return /^https:\/\//i.test(url) ? url : undefined
}

/** One entry per line; blank lines are dropped. Places can contain commas ("Remote, Australia"). */
export function parseLines(text: string): string[] {
  return text
    .split('\n')
    .map((line) => line.trim())
    .filter((line) => line.length > 0)
}
