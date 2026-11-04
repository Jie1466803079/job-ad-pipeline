import { describe, expect, it } from 'vitest'
import { parseRoute, routeHash, tabFor, type Route } from './route.ts'

describe('parseRoute', () => {
  it('reads queue tabs and ad ids', () => {
    expect(parseRoute('#/queue/tracked')).toEqual({ page: 'queue', tab: 'tracked' })
    expect(parseRoute('#/postings/12')).toEqual({ page: 'posting', id: 12 })
  })

  it('falls back to the review tab for anything else', () => {
    for (const hash of ['', '#', '#/', '#/queue/nope', '#/postings/abc', '#/postings/', '#/other']) {
      expect(parseRoute(hash)).toEqual({ page: 'queue', tab: 'review' })
    }
  })

  it('round-trips through routeHash', () => {
    const routes: Route[] = [
      { page: 'queue', tab: 'closed' },
      { page: 'posting', id: 7 },
    ]
    for (const route of routes) expect(parseRoute(routeHash(route))).toEqual(route)
  })
})

describe('tabFor', () => {
  it('lists applications under applied, even once closed', () => {
    expect(tabFor('interview', true)).toBe('applied')
    expect(tabFor('tracked', true)).toBe('closed')
    expect(tabFor('tracked', false)).toBe('tracked')
    expect(tabFor('dismissed', true)).toBe('dismissed')
  })
})
