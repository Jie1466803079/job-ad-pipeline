// Turns quote spans from the API into pieces of text to highlight. Spans count Unicode
// code points, as Python strings do, so the text is split with Array.from instead of
// being indexed directly: an emoji is one code point but two UTF-16 units.

import type { PostingDetail, Skill } from './api.ts'
import { FIELD_LABELS } from './format.ts'

export interface Mark {
  start: number
  end: number
  field: string
  label: string
}

export interface Segment {
  text: string
  marks: Mark[]
}

/** Cuts the text at every mark boundary. Each piece lists the marks that cover it, so overlaps show. */
export function buildSegments(text: string, marks: Mark[]): Segment[] {
  const chars = Array.from(text)
  const usable = marks
    .map((mark) => ({ ...mark, start: Math.max(0, mark.start), end: Math.min(chars.length, mark.end) }))
    .filter((mark) => mark.start < mark.end)
  const cuts = [...new Set([0, chars.length, ...usable.flatMap((mark) => [mark.start, mark.end])])].sort(
    (a, b) => a - b,
  )
  const segments: Segment[] = []
  for (let i = 0; i + 1 < cuts.length; i++) {
    const start = cuts[i]!
    const end = cuts[i + 1]!
    segments.push({
      text: chars.slice(start, end).join(''),
      marks: usable.filter((mark) => mark.start <= start && end <= mark.end),
    })
  }
  return segments
}

/** The marks for every verified quote on the detail page: routing fields first, then skills. */
export function marksFor(detail: Pick<PostingDetail, 'fields' | 'skills'>): Mark[] {
  const marks: Mark[] = []
  for (const field of detail.fields) {
    if (field.span) {
      marks.push({ start: field.span[0], end: field.span[1], field: field.name, label: FIELD_LABELS[field.name] })
    }
  }
  const addSkills = (skills: Skill[], field: string, label: string) => {
    for (const skill of skills) {
      if (skill.span) marks.push({ start: skill.span[0], end: skill.span[1], field, label: `${label}: ${skill.skill}` })
    }
  }
  addSkills(detail.skills.required, 'required_skills', 'Required skill')
  addSkills(detail.skills.nice_to_have, 'nice_to_have_skills', 'Nice-to-have skill')
  return marks
}
