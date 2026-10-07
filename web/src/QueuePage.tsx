import { api, type QueueItem, type Tab } from './api.ts'
import { TAB_LABELS, dateLabel, valueLabel } from './format.ts'
import { routeHash } from './route.ts'
import { useLoader } from './useLoader.ts'

const MAIN_TABS: Tab[] = ['review', 'tracked', 'ineligible', 'applied', 'closed']
const MORE_TABS: Tab[] = ['skipped', 'dismissed']

export function QueuePage({ tab, counts }: { tab: Tab; counts: Record<Tab, number> | undefined }) {
  const queue = useLoader(`queue/${tab}`, () => api.queue(tab))
  return (
    <section>
      <nav className="tabs">
        {MAIN_TABS.map((name) => (
          <TabLink key={name} tab={name} active={name === tab} count={counts?.[name]} />
        ))}
        <details className="more-tabs" open={MORE_TABS.includes(tab)}>
          <summary>Skipped and dismissed</summary>
          {MORE_TABS.map((name) => (
            <TabLink key={name} tab={name} active={name === tab} count={counts?.[name]} />
          ))}
        </details>
      </nav>
      {queue.error && <p className="error">{queue.error}</p>}
      {!queue.data && !queue.error && <p className="page-message">Loading...</p>}
      {queue.data && <QueueTable tab={tab} items={queue.data.items} total={queue.data.total} />}
    </section>
  )
}

function TabLink({ tab, active, count }: { tab: Tab; active: boolean; count: number | undefined }) {
  return (
    <a
      href={routeHash({ page: 'queue', tab })}
      className={active ? 'tab active' : 'tab'}
      aria-current={active ? 'page' : undefined}
    >
      {TAB_LABELS[tab]}
      {count !== undefined && <span className="count">{count}</span>}
    </a>
  )
}

function QueueTable({ tab, items, total }: { tab: Tab; items: QueueItem[]; total: number }) {
  if (items.length === 0) return <p className="page-message">Nothing here.</p>
  const showWhy = tab === 'review' || tab === 'skipped'
  return (
    <>
      {total > items.length && (
        <p className="muted">
          Showing the first {items.length} of {total}.
        </p>
      )}
      <table className="queue">
        <thead>
          <tr>
            <th>Company</th>
            <th>Title</th>
            <th>Location</th>
            <th>Work rights</th>
            <th>Closes</th>
            <th>Fit</th>
            <th>Status</th>
            {showWhy && <th>Why</th>}
          </tr>
        </thead>
        <tbody>
          {items.map((item) => (
            <tr key={item.id}>
              <td>{item.company}</td>
              <td>
                <a href={routeHash({ page: 'posting', id: item.id })}>{item.title}</a>
              </td>
              <td>{item.locations.join('; ')}</td>
              <td>{item.work_rights ? valueLabel(item.work_rights) : ''}</td>
              <td>{item.closing_date ? dateLabel(item.closing_date) : ''}</td>
              <td>{item.fit && item.fit.total > 0 ? `${item.fit.matched}/${item.fit.total}` : ''}</td>
              <td>
                {valueLabel(item.status)}
                {item.closed && ' (closed)'}
              </td>
              {showWhy && <td className="why">{item.skip_reason ?? item.reasons.join('; ')}</td>}
            </tr>
          ))}
        </tbody>
      </table>
    </>
  )
}
