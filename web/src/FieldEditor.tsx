import { useState, type ReactNode } from 'react'
import type { FieldEdit, FieldView, Salary } from './api.ts'
import { parseLines, valueLabel } from './format.ts'

const PERIODS = ['year', 'month', 'day', 'hour']

interface EditorProps<T> {
  initial: T
  busy: boolean
  onSave: (value: T) => void
  onCancel: () => void
}

interface FieldEditorProps {
  field: FieldView
  busy: boolean
  onSave: (edit: FieldEdit) => void
  onCancel: () => void
}

/** The right control for each kind of field. */
export function FieldEditor({ field, busy, onSave, onCancel }: FieldEditorProps) {
  const common = { busy, onCancel }
  switch (field.name) {
    case 'locations':
      return <PlacesEditor {...common} initial={field.value} onSave={(value) => onSave({ locations: value })} />
    case 'salary':
      return <SalaryEditor {...common} initial={field.value} onSave={(value) => onSave({ salary: value })} />
    case 'closing_date':
      return <DateEditor {...common} initial={field.value} onSave={(value) => onSave({ closing_date: value })} />
    default:
      return (
        <ChoiceEditor
          {...common}
          initial={field.value}
          options={field.options ?? []}
          onSave={(value) => onSave({ [field.name]: value })}
        />
      )
  }
}

function EditorForm(props: { busy: boolean; onSubmit: () => void; onCancel: () => void; children: ReactNode }) {
  return (
    <form
      className="editor"
      onSubmit={(event) => {
        event.preventDefault()
        props.onSubmit()
      }}
    >
      {props.children}
      <div className="editor-buttons">
        <button type="submit" disabled={props.busy}>
          Save
        </button>
        <button type="button" className="link" onClick={props.onCancel}>
          Cancel
        </button>
      </div>
    </form>
  )
}

function ChoiceEditor({ initial, options, busy, onSave, onCancel }: EditorProps<string> & { options: string[] }) {
  const [value, setValue] = useState(initial)
  return (
    <EditorForm busy={busy} onCancel={onCancel} onSubmit={() => onSave(value)}>
      <select value={value} onChange={(event) => setValue(event.target.value)}>
        {options.map((option) => (
          <option key={option} value={option}>
            {valueLabel(option)}
          </option>
        ))}
      </select>
    </EditorForm>
  )
}

function DateEditor({ initial, busy, onSave, onCancel }: EditorProps<string>) {
  const [notStated, setNotStated] = useState(initial === 'not_stated')
  const [value, setValue] = useState(initial === 'not_stated' ? '' : initial)
  return (
    <EditorForm busy={busy} onCancel={onCancel} onSubmit={() => onSave(notStated ? 'not_stated' : value)}>
      <input
        type="date"
        value={value}
        required={!notStated}
        disabled={notStated}
        onChange={(event) => setValue(event.target.value)}
      />
      <label>
        <input type="checkbox" checked={notStated} onChange={(event) => setNotStated(event.target.checked)} /> Not
        stated
      </label>
    </EditorForm>
  )
}

function PlacesEditor({ initial, busy, onSave, onCancel }: EditorProps<string[]>) {
  const [text, setText] = useState(initial.join('\n'))
  return (
    <EditorForm busy={busy} onCancel={onCancel} onSubmit={() => onSave(parseLines(text))}>
      <textarea rows={3} value={text} onChange={(event) => setText(event.target.value)} />
      <span className="muted">One place per line, for example "Sydney" or "Remote, Australia".</span>
    </EditorForm>
  )
}

function SalaryEditor({ initial, busy, onSave, onCancel }: EditorProps<Salary>) {
  const [stated, setStated] = useState(initial.stated)
  const [min, setMin] = useState(initial.stated ? String(initial.min) : '')
  const [max, setMax] = useState(initial.stated ? String(initial.max) : '')
  const [currency, setCurrency] = useState(initial.currency || 'AUD')
  const [period, setPeriod] = useState(initial.period === 'not_stated' ? 'year' : initial.period)
  const save = () => onSave({ stated, min: Number(min), max: Number(max), currency, period })
  return (
    <EditorForm busy={busy} onCancel={onCancel} onSubmit={save}>
      <label>
        <input type="checkbox" checked={stated} onChange={(event) => setStated(event.target.checked)} /> Stated in
        the ad
      </label>
      {stated && (
        <div className="salary-inputs">
          <input
            type="number"
            min="0"
            step="any"
            required
            aria-label="Minimum"
            value={min}
            onChange={(event) => setMin(event.target.value)}
          />
          to
          <input
            type="number"
            min="0"
            step="any"
            required
            aria-label="Maximum"
            value={max}
            onChange={(event) => setMax(event.target.value)}
          />
          <input aria-label="Currency" size={4} value={currency} onChange={(event) => setCurrency(event.target.value)} />
          per
          <select aria-label="Pay period" value={period} onChange={(event) => setPeriod(event.target.value)}>
            {PERIODS.map((choice) => (
              <option key={choice} value={choice}>
                {choice}
              </option>
            ))}
          </select>
        </div>
      )}
    </EditorForm>
  )
}
