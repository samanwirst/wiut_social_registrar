import { useCallback, useEffect, useState } from 'react';
import { Button, Caption, Cell, List, Placeholder, Section, Spinner } from '@telegram-apps/telegram-ui';
import { api } from './api';
import { useRemoteResource } from './hooks/useRemoteResource';
import { Pagination } from './Pagination';
import { openTelegramChat } from './telegram';
import type { BroadcastsPage } from './types';

export function Broadcasts({ formId }: { formId: string }) {
  const [page, setPage] = useState(0);
  const load = useCallback((signal: AbortSignal) => api<BroadcastsPage>(`/api/forms/${encodeURIComponent(formId)}/broadcasts?status=completed&page=${page}`, { signal }), [formId, page]);
  const { data, loading, error, reload } = useRemoteResource(load);
  useEffect(() => {
    if (!data?.has_active) return;
    const timer = window.setInterval(reload, 5000);
    return () => window.clearInterval(timer);
  }, [data?.has_active, reload]);
  return <Section className="studio-section broadcast-history" header="Messages" footer="Tap Finished to view the sent message in Telegram">
    <div className="table-tools"><Caption>{data?.total ?? '…'} finished</Caption><Button type="button" size="s" mode="bezeled" aria-label="Refresh messages" disabled={loading} onClick={reload}>Refresh</Button></div>
    {error ? <Caption role="alert" className="danger notice">{error}</Caption> : null}
    {loading && !data ? <div className="loading"><Spinner size="m" /></div> : data?.broadcasts.length ? <List>
      {data.broadcasts.map(item => <Cell Component="a" className="broadcast-entry" key={item.id} multiline href={item.message_url || undefined}
        onClick={e => { e.preventDefault(); if (item.message_url) openTelegramChat(item.message_url); }}
        subtitle={new Date(item.created_at).toLocaleString()}
        description={<Caption>Sent {item.counts.sent || 0} / {item.total} · Failed {item.counts.failed || 0} · Unconfirmed {item.counts.unknown || 0}</Caption>}>Finished</Cell>)}
    </List> : <Placeholder header="No finished messages yet" description="Completed broadcasts will appear here" />}
    {data ? <Pagination {...data} disabled={loading} onPage={setPage} /> : null}
  </Section>;
}
