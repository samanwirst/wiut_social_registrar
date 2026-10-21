import { useCallback, useEffect, useRef, useState } from 'react';
import { AppRoot, Button, Caption, Placeholder, Snackbar, Spinner } from '@telegram-apps/telegram-ui';
import { api, errorMessage } from './api';
import { EventEditor } from './EventEditor';
import { EventList } from './EventList';
import { supports, telegram, useTelegramTheme } from './telegram';
import type { EventDetails, EventsPage } from './types';

function Workspace() {
  const [events, setEvents] = useState<EventsPage | null>(null);
  const [event, setEvent] = useState<EventDetails | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState<{ message: string; error: boolean } | null>(null);
  const [retry, setRetry] = useState(0);
  const guard = useRef(() => true);
  const navigating = useRef(false);
  const notify = useCallback((message: string, error = false) => setNotice({ message, error }), []);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setError('');
    telegram?.ready(); telegram?.expand();
    const id = new URLSearchParams(location.search).get('event');
    Promise.all([
      api('/api/session', { signal: controller.signal }),
      id ? api<EventDetails>(`/api/events/${encodeURIComponent(id)}`, { signal: controller.signal })
        : api<EventsPage>('/api/events', { signal: controller.signal }),
    ]).then(([, data]) => {
      if (controller.signal.aborted) return;
      if ('events' in data) setEvents(data); else setEvent(data);
    }).catch(error => { if (!controller.signal.aborted) setError(errorMessage(error)); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [retry]);

  const loadEvents = useCallback(async (page: number) => {
    if (navigating.current || !guard.current()) return;
    navigating.current = true; setLoading(true);
    try { const data = await api<EventsPage>(`/api/events?page=${page}`); setEvents(data); setEvent(null); setError(''); }
    catch (error) { notify(errorMessage(error), true); }
    finally { navigating.current = false; setLoading(false); }
  }, [notify]);
  const openEvent = async (id: string) => {
    if (navigating.current) return;
    navigating.current = true; setLoading(true);
    try { setEvent(await api<EventDetails>(`/api/events/${encodeURIComponent(id)}`)); }
    catch (error) { notify(errorMessage(error), true); }
    finally { navigating.current = false; setLoading(false); }
  };
  const listPage = events?.page ?? 0;
  useEffect(() => {
    if (!supports('6.1')) return;
    const back = () => { void loadEvents(listPage); };
    if (event) telegram?.BackButton?.show(); else telegram?.BackButton?.hide();
    telegram?.BackButton?.onClick(back);
    return () => { telegram?.BackButton?.offClick?.(back); telegram?.BackButton?.hide(); };
  }, [event?.id, listPage, loadEvents]);

  return <>
    {event ? <header className="brandbar"><Button type="button" mode="plain" size="s" disabled={loading} onClick={() => { void loadEvents(listPage); }}>
      ← All events</Button><Caption className="muted">Event Studio</Caption></header> : null}
    <main className="page" aria-busy={loading}>
      {error ? <Placeholder header="We couldn't open your workspace" description={error}
        action={<Button type="button" mode="bezeled" onClick={() => setRetry(value => value + 1)}>Try again</Button>} />
        : event ? <fieldset className="editor-fieldset" disabled={loading}><EventEditor key={event.id} event={event} guard={guard} notify={notify} onSaved={setEvent} /></fieldset>
          : events ? <EventList data={events} busy={loading} onOpen={openEvent} onPage={page => { void loadEvents(page); }} />
            : <div className="loading" role="status"><Spinner size="l" /><span>Opening your workspace…</span></div>}
    </main>
    {notice ? <Snackbar key={notice.message} onClose={() => setNotice(null)} duration={notice.error ? 6500 : 3500}
      role="status" description={notice.message}>{notice.error ? 'Please try again' : 'Done'}</Snackbar> : null}
  </>;
}

export function App() {
  const theme = useTelegramTheme();
  return <AppRoot {...theme} className="event-studio">
    {telegram?.initData ? <Workspace /> : <main className="page"><Placeholder header="Open Event Studio in Telegram"
      description="Use /panel in your private chat with the bot. Finish student registration and create an event to manage it here." /></main>}
  </AppRoot>;
}
