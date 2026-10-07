// Hash routes: #/queue/<tab> and #/postings/<id>. intake-api only ever serves one page.

import { TABS, type Tab } from './api.ts'

export type Route = { page: 'queue'; tab: Tab } | { page: 'posting'; id: number }

export function parseRoute(hash: string): Route {
  const [page, value] = hash.replace(/^#\/?/, '').split('/')
  if (page === 'postings' && value && /^\d+$/.test(value)) return { page: 'posting', id: Number(value) }
  if (page === 'queue' && isTab(value)) return { page: 'queue', tab: value }
  return { page: 'queue', tab: 'review' }
}

export function routeHash(route: Route): string {
  return route.page === 'posting' ? `#/postings/${route.id}` : `#/queue/${route.tab}`
}

/** The queue tab an ad with this status is listed under. */
export function tabFor(status: string, closed: boolean): Tab {
  if (['applied', 'interview', 'offer', 'rejected'].includes(status)) return 'applied'
  if (status === 'skipped' || status === 'dismissed') return status
  if (closed) return 'closed'
  return isTab(status) ? status : 'review'
}

function isTab(value: string | undefined): value is Tab {
  return TABS.some((tab) => tab === value)
}
