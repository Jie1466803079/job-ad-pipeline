import { describe, expect, it } from 'vitest'
import { detailText } from './api.ts'

describe('detailText', () => {
  it('reads the error bodies FastAPI sends', () => {
    expect(detailText({ detail: 'Wrong username or password.' }, 401)).toBe('Wrong username or password.')
    const invalid = { detail: [{ msg: 'Input should be a valid date' }, { msg: 'Field required' }] }
    expect(detailText(invalid, 422)).toBe('Input should be a valid date; Field required')
  })

  it('falls back to the status code', () => {
    expect(detailText('Internal Server Error', 500)).toBe('The request failed (500).')
    expect(detailText(null, 502)).toBe('The request failed (502).')
  })
})
