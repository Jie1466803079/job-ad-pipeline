import { describe, expect, it } from 'vitest'
import type { FieldView, Salary } from './api.ts'
import { buildSegments, marksFor, type Mark } from './highlight.ts'

function mark(start: number, end: number, field = 'work_rights'): Mark {
  return { start, end, field, label: field }
}

function pieces(text: string, marks: Mark[]): [string, string[]][] {
  return buildSegments(text, marks).map((segment) => [segment.text, segment.marks.map((m) => m.field)])
}

describe('buildSegments', () => {
  it('returns the whole text when nothing is marked', () => {
    expect(pieces('Sydney office', [])).toEqual([['Sydney office', []]])
  })

  it('marks one quote in the middle', () => {
    expect(pieces('Join us in Sydney today', [mark(11, 17, 'locations')])).toEqual([
      ['Join us in ', []],
      ['Sydney', ['locations']],
      [' today', []],
    ])
  })

  it('splits overlapping quotes so the shared part carries both fields', () => {
    expect(pieces('abcdefgh', [mark(1, 5, 'a'), mark(3, 7, 'b')])).toEqual([
      ['a', []],
      ['bc', ['a']],
      ['de', ['a', 'b']],
      ['fg', ['b']],
      ['h', []],
    ])
  })

  it('keeps two quotes of the same sentence in one piece', () => {
    expect(pieces('Python and SQL', [mark(0, 14, 'skill'), mark(0, 14, 'skill')])).toEqual([
      ['Python and SQL', ['skill', 'skill']],
    ])
  })

  it('counts an emoji as one character, as the Python service does', () => {
    const rocket = String.fromCodePoint(0x1f680)
    // In Python, "Sydney" starts at 13 here: the rocket is one code point but two UTF-16 units.
    expect(pieces(`${rocket} Join us in Sydney`, [mark(13, 19, 'locations')])[1]).toEqual(['Sydney', ['locations']])
  })

  it('clamps spans to the text and drops empty or reversed ones', () => {
    expect(pieces('abcdef', [mark(-3, 2, 'x'), mark(4, 99, 'y'), mark(3, 3, 'z'), mark(5, 1, 'w')])).toEqual([
      ['ab', ['x']],
      ['cd', []],
      ['ef', ['y']],
    ])
  })

  it('returns nothing for empty text', () => {
    expect(buildSegments('', [mark(0, 3)])).toEqual([])
  })
})

describe('marksFor', () => {
  it('collects the verified quotes of fields and skills', () => {
    const none: Salary = { stated: false, min: 0, max: 0, currency: '', period: 'not_stated' }
    const common = { quote: '', checks: [], edited: false, options: null }
    const fields: FieldView[] = [
      { ...common, name: 'work_mode', value: 'hybrid', extracted: 'hybrid', span: [5, 16] },
      { ...common, name: 'salary', value: none, extracted: none, span: null },
    ]
    const skills = {
      required: [
        { skill: 'Python', quote: 'Python', verified: true, span: [20, 26] as [number, number] },
        { skill: 'Go', quote: 'Go', verified: false, span: null },
      ],
      nice_to_have: [],
    }
    expect(marksFor({ fields, skills })).toEqual([
      { start: 5, end: 16, field: 'work_mode', label: 'Work mode' },
      { start: 20, end: 26, field: 'required_skills', label: 'Required skill: Python' },
    ])
  })
})
