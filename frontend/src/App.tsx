import { useCallback, useState } from 'react';
import { AppRoot, Button, Caption, Placeholder, Snackbar, Spinner } from '@telegram-apps/telegram-ui';
import { useWorkspace } from './hooks/useWorkspace';
import { EventEditor } from './EventEditor';
import { EventList } from './EventList';
import { telegram, useTelegramTheme } from './telegram';

function Workspace() {
  const [notice, setNotice] = useState<{ message: string; error: boolean } | null>(null);
  const notify = useCallback((message: string, error = false) => setNotice({ message, error }), []);
  const { event, events, loading, error, retry, guard, listPage, loadEvents, openEvent, onSaved } = useWorkspace(notify);

  return <>
    {event ? <header className="brandbar"><Button type="button" mode="plain" size="s" disabled={loading} onClick={() => { void loadEvents(listPage); }}>
      ← All events</Button><Caption className="muted">Event Studio</Caption></header> : null}
    <main className="page" aria-busy={loading}>
      {error ? <Placeholder header="We couldn't open your workspace" description={error}
        action={<Button type="button" mode="bezeled" onClick={retry}>Try again</Button>} />
        : event ? <fieldset className="editor-fieldset" disabled={loading}><EventEditor key={event.id} event={event} guard={guard} notify={notify} onSaved={onSaved} /></fieldset>
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
