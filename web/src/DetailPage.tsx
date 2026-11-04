import { useState } from 'react'
import { api, messageOf, type FieldEdit, type FieldView, type PostingDetail, type Skill } from './api.ts'
import { FieldEditor } from './FieldEditor.tsx'
import {
  FIELD_LABELS,
  checkLabel,
  dateLabel,
  decisionLabel,
  fieldValueLabel,
  historyLabel,
  safeUrl,
  timeLabel,
  valueLabel,
} from './format.ts'
import { buildSegments, marksFor } from './highlight.ts'
import { routeHash, tabFor } from './route.ts'
import { useLoader } from './useLoader.ts'

type Run = (action: () => Promise<PostingDetail>) => Promise<boolean>

export function DetailPage({ id, onChange }: { id: number; onChange: () => void }) {
  const posting = useLoader(`posting/${id}`, () => api.posting(id))
  const [busy, setBusy] = useState(false)
  const [actionError, setActionError] = useState<string>()

  const run: Run = async (action) => {
    setBusy(true)
    setActionError(undefined)
    try {
      posting.replace(await action())
      onChange()
      return true
    } catch (reason) {
      setActionError(messageOf(reason))
      return false
    } finally {
      setBusy(false)
    }
  }

  if (posting.error) return <p className="page-message error">{posting.error}</p>
  if (!posting.data) return <p className="page-message">Loading...</p>
  const ad = posting.data
  const link = safeUrl(ad.url)

  return (
    <article className="detail">
      <header className="detail-header">
        <a href={routeHash({ page: 'queue', tab: tabFor(ad.status, ad.closed_at !== null) })}>Back to the list</a>
        <h1>{ad.title}</h1>
        <p className="muted">
          {ad.company} | {valueLabel(ad.status)}
          {ad.closed_at !== null && ' (closed)'}
          {ad.closing_date && ` | closes ${dateLabel(ad.closing_date)}`}
          {link && (
            <>
              {' | '}
              <a href={link} target="_blank" rel="noreferrer">
                Open the ad
              </a>
            </>
          )}
        </p>
        <Actions ad={ad} busy={busy} run={run} />
        {actionError && (
          <p className="error" role="alert">
            {actionError}
          </p>
        )}
      </header>
      <div className="detail-columns">
        <AdText ad={ad} />
        <aside className="facts">
          <ExtractionNote ad={ad} />
          {ad.fields.map((field) => (
            <FieldCard
              key={field.name}
              field={field}
              canEdit={ad.actions.can_edit}
              busy={busy}
              onSave={(edit) => run(() => api.correct(ad.id, edit))}
            />
          ))}
          <Skills ad={ad} />
          <History ad={ad} />
        </aside>
      </div>
    </article>
  )
}

function Actions({ ad, busy, run }: { ad: PostingDetail; busy: boolean; run: Run }) {
  const { decisions, statuses } = ad.actions
  if (decisions.length === 0 && statuses.length === 0) return null
  return (
    <div className="actions">
      {decisions.map((decision) => (
        <button
          key={decision}
          type="button"
          className={`decision decision-${decision}`}
          disabled={busy}
          onClick={() => void run(() => api.decide(ad.id, decision))}
        >
          {decisionLabel(decision, ad.status)}
        </button>
      ))}
      {statuses.length > 0 && (
        <label>
          Application status{' '}
          <select
            value={ad.status}
            disabled={busy}
            onChange={(event) => {
              const status = statuses.find((choice) => choice === event.target.value)
              if (status) void run(() => api.setStatus(ad.id, status))
            }}
          >
            {statuses.map((status) => (
              <option key={status} value={status}>
                {valueLabel(status)}
              </option>
            ))}
          </select>
        </label>
      )}
    </div>
  )
}

/** The ad text with every verified quote highlighted. The text is rendered as text, never as HTML. */
function AdText({ ad }: { ad: PostingDetail }) {
  if (ad.text === null) {
    return (
      <section className="ad-text muted">
        The ad text was deleted 30 days after the ad closed. The extracted values are kept.
      </section>
    )
  }
  return (
    <section className="ad-text" aria-label="Ad text">
      {buildSegments(ad.text, marksFor(ad)).map((segment, index) => {
        const first = segment.marks[0]
        if (!first) return <span key={index}>{segment.text}</span>
        const classes = `hl hl-${first.field}${segment.marks.length > 1 ? ' hl-multi' : ''}`
        return (
          <mark key={index} className={classes} title={segment.marks.map((mark) => mark.label).join('; ')}>
            {segment.text}
          </mark>
        )
      })}
    </section>
  )
}

function ExtractionNote({ ad }: { ad: PostingDetail }) {
  const { extraction } = ad
  if (!extraction) {
    return (
      <p className="note">
        {ad.skip_reason ? `Skipped before extraction: ${ad.skip_reason}` : 'There is no extraction of this ad text.'}
      </p>
    )
  }
  if (extraction.failed) {
    return (
      <p className="note error">
        The extraction by {extraction.model} failed: {extraction.reasons.join('; ')}
      </p>
    )
  }
  return (
    <p className="note">
      Extracted by {extraction.model} and routed to {valueLabel(extraction.route)}
      {extraction.reasons.length > 0 ? ` because ${extraction.reasons.join('; ')}` : '.'}
    </p>
  )
}

interface FieldCardProps {
  field: FieldView
  canEdit: boolean
  busy: boolean
  onSave: (edit: FieldEdit) => Promise<boolean>
}

function FieldCard({ field, canEdit, busy, onSave }: FieldCardProps) {
  const [editing, setEditing] = useState(false)
  const checks = field.checks.filter((check) => check.status !== 'na')
  return (
    <section className="field">
      <h3>
        <span className={`swatch hl-${field.name}`} />
        {FIELD_LABELS[field.name]}
      </h3>
      <p className="value">
        {fieldValueLabel(field)}
        {field.edited && <span className="badge">corrected</span>}
      </p>
      {field.edited && <p className="muted">The model said: {fieldValueLabel(field, 'extracted')}</p>}
      {field.quote && <blockquote>{field.quote}</blockquote>}
      {checks.length > 0 && (
        <ul className="checks">
          {checks.map((check) => (
            <li key={check.name} className={check.status}>
              {checkLabel(check)}
            </li>
          ))}
        </ul>
      )}
      {canEdit &&
        (editing ? (
          <FieldEditor
            field={field}
            busy={busy}
            onCancel={() => setEditing(false)}
            onSave={async (edit) => {
              if (await onSave(edit)) setEditing(false)
            }}
          />
        ) : (
          <button type="button" className="link" onClick={() => setEditing(true)}>
            Correct
          </button>
        ))}
    </section>
  )
}

function Skills({ ad }: { ad: PostingDetail }) {
  const { required, nice_to_have: niceToHave } = ad.skills
  if (!ad.fit && required.length === 0 && niceToHave.length === 0) return null
  return (
    <section className="field">
      <h3>Skills</h3>
      {ad.fit && <p className="value">{ad.fit.summary}</p>}
      <SkillList title="Required" skills={required} field="required_skills" />
      <SkillList title="Nice to have" skills={niceToHave} field="nice_to_have_skills" />
    </section>
  )
}

function SkillList({ title, skills, field }: { title: string; skills: Skill[]; field: string }) {
  if (skills.length === 0) return null
  return (
    <>
      <h4>{title}</h4>
      <ul className="skills">
        {skills.map((skill, index) => (
          <li key={index} className={skill.verified ? `hl-${field}` : 'unverified'} title={skill.quote}>
            {skill.skill}
            {!skill.verified && ' (quote not found)'}
          </li>
        ))}
      </ul>
    </>
  )
}

function History({ ad }: { ad: PostingDetail }) {
  return (
    <section className="field">
      <h3>History</h3>
      <ol className="history">
        {ad.history.map((event, index) => (
          <li key={index}>
            <time dateTime={event.at}>{timeLabel(event.at)}</time> {historyLabel(event)}
          </li>
        ))}
      </ol>
    </section>
  )
}
