import { describe, expect, it } from 'vitest'
import type { FieldView, HistoryEvent, Salary, Stats } from './api.ts'
import {
  checkLabel,
  dateLabel,
  decisionLabel,
  fieldValueLabel,
  historyLabel,
  parseLines,
  safeUrl,
  salaryLabel,
  statsLine,
  timeLabel,
  valueLabel,
} from './format.ts'

const salary: Salary = { stated: true, min: 120000, max: 140000, currency: 'AUD', period: 'year' }
type ReviewEvent = Extract<HistoryEvent, { kind: 'review' }>

function reviewEvent(action: ReviewEvent['action'], extra: Partial<ReviewEvent> = {}): HistoryEvent {
  const at = '2026-10-07T09:00:00+11:00'
  return { kind: 'review', at, username: 'jie', action, fields: [], from_status: null, to_status: null, ...extra }
}

describe('valueLabel', () => {
  it('turns codes into words and keeps abbreviations upper case', () => {
    expect(valueLabel('citizen_or_pr')).toBe('citizen or PR')
    expect(valueLabel('nv1')).toBe('NV1')
    expect(valueLabel('not_stated')).toBe('not stated')
  })
})

describe('dateLabel', () => {
  it('writes ISO dates the Australian way', () => {
    expect(dateLabel('2026-10-31')).toBe('31 Oct 2026')
    expect(dateLabel('2026-01-05')).toBe('5 Jan 2026')
  })

  it('says not stated for missing dates', () => {
    expect(dateLabel(null)).toBe('not stated')
    expect(dateLabel('not_stated')).toBe('not stated')
  })
})

describe('salaryLabel', () => {
  it('writes a range with its period', () => {
    expect(salaryLabel(salary)).toBe('AUD 120,000 to 140,000 per year')
    expect(salaryLabel({ ...salary, max: 120000, currency: '' })).toBe('120,000 per year')
    expect(salaryLabel({ ...salary, stated: false })).toBe('not stated')
  })
})

describe('fieldValueLabel', () => {
  it('formats each kind of field', () => {
    const common = { quote: '', span: null, checks: [], edited: true, options: null }
    const places: FieldView = { ...common, name: 'locations', value: ['Sydney', 'Remote, Australia'], extracted: [] }
    const closing: FieldView = { ...common, name: 'closing_date', value: '2026-10-31', extracted: 'not_stated' }
    const rights: FieldView = { ...common, name: 'work_rights', value: 'citizen_or_pr', extracted: 'any_work_rights' }
    const pay: FieldView = { ...common, name: 'salary', value: salary, extracted: salary }
    expect(fieldValueLabel(places)).toBe('Sydney; Remote, Australia')
    expect(fieldValueLabel(places, 'extracted')).toBe('not stated')
    expect(fieldValueLabel(closing)).toBe('31 Oct 2026')
    expect(fieldValueLabel(rights, 'extracted')).toBe('any work rights')
    expect(fieldValueLabel(pay)).toBe('AUD 120,000 to 140,000 per year')
  })
})

describe('checkLabel and decisionLabel', () => {
  it('describe checks and buttons', () => {
    expect(checkLabel({ name: 'quote_found', status: 'fail', reason: 'quote not found in the ad' })).toBe(
      'Quote found in the ad: no (quote not found in the ad)',
    )
    expect(checkLabel({ name: 'matches_quote', status: 'pass', reason: '' })).toBe('Value matches the quote: yes')
    expect(checkLabel({ name: 'quote_found', status: 'pass', reason: 'not stated' })).toBe(
      'Nothing stated, so there is no quote to check',
    )
    expect(decisionLabel('approve', 'review')).toBe('Approve')
    expect(decisionLabel('approve', 'dismissed')).toBe('Restore')
    expect(decisionLabel('approve', 'skipped')).toBe('Track anyway')
    expect(decisionLabel('override_ineligible', 'ineligible')).toBe('Track anyway')
  })
})

describe('historyLabel', () => {
  it('describes extractions and reviewer actions', () => {
    const at = '2026-10-07T09:00:00+11:00'
    const extraction = { kind: 'extraction', at, model: 'gemini-3.8-flash', route: 'review', failed: false } as const
    expect(historyLabel(extraction)).toBe('Extracted by gemini-3.8-flash and routed to review')
    expect(historyLabel({ ...extraction, failed: true })).toBe('Extraction by gemini-3.8-flash failed')
    expect(historyLabel(reviewEvent('edit', { fields: ['work_rights', 'closing_date'] }))).toBe(
      'jie corrected Work rights, Closing date',
    )
    expect(historyLabel(reviewEvent('approve'))).toBe('jie approved it')
    expect(historyLabel(reviewEvent('set_status', { to_status: 'interview' }))).toBe('jie set the status to interview')
  })
})

describe('timeLabel', () => {
  it('shows Sydney time', () => {
    expect(timeLabel('2026-10-06T21:00:00Z')).toContain('7 Oct 2026')
  })
})

describe('statsLine', () => {
  it('sums up today and this month', () => {
    const tabs = { review: 0, tracked: 0, ineligible: 0, applied: 0, closed: 0, skipped: 0, dismissed: 0 }
    const today = { fetched: 24, created: 9, skipped: 7, tracked: 2, review: 0, ineligible: 0, closed: 1, failed: 0 }
    const stats: Stats = { tabs, today, month: { extracted: 4, auto_routed: 3, llm_cost_usd: 0.0235 } }
    expect(statsLine(stats)).toBe(
      'Today: 24 fetched, 9 new, 2 tracked, 0 to review. This month: US$0.02 of LLM calls, 75% routed without review.',
    )
    expect(statsLine({ ...stats, month: { extracted: 0, auto_routed: 0, llm_cost_usd: 0 } })).toContain(
      'nothing extracted yet',
    )
  })
})

describe('safeUrl and parseLines', () => {
  it('keeps only https links', () => {
    expect(safeUrl('https://jobs.lever.co/mable/1')).toBe('https://jobs.lever.co/mable/1')
    expect(safeUrl('javascript:alert(1)')).toBeUndefined()
    expect(safeUrl('http://example.com')).toBeUndefined()
  })

  it('reads one place per line', () => {
    expect(parseLines(' Sydney \n\nRemote, Australia\n')).toEqual(['Sydney', 'Remote, Australia'])
  })
})
