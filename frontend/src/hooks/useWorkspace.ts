import { useCallback, useEffect, useRef, useState } from 'react';
import { api, errorMessage } from '../api';
import { telegram, useTelegramBack } from '../telegram';
import type { EventDetails, EventsPage, Notify } from '../types';
import { useRemoteResource } from './useRemoteResource';

type WorkspaceData = EventDetails | EventsPage;

export function useWorkspace(notify: Notify) {
  const [initialEventId] = useState(() => new URLSearchParams(location.search).get('event'));
  const load = useCallback(async (signal: AbortSignal): Promise<WorkspaceData> => {
    const path = initialEventId ? `/api/events/${encodeURIComponent(initialEventId)}` : '/api/events';
    const [, data] = await Promise.all([
      api('/api/session', { signal }), api<WorkspaceData>(path, { signal }),
    ]);
    return data;
  }, [initialEventId]);
  const initial = useRemoteResource(load);
  const [view, setView] = useState<WorkspaceData | null>(null);
  const [listPage, setListPage] = useState(0);
  const [navigating, setNavigating] = useState(false);
  const navigationPending = useRef(false);
  const guard = useRef(() => true);
  const current = view ?? initial.data;
  const events = current && 'events' in current ? current : null;
  const event = current && !('events' in current) ? current : null;

  useEffect(() => { telegram?.ready(); telegram?.expand(); }, []);

  const navigate = useCallback(async (path: string) => {
    if (navigationPending.current) return;
    navigationPending.current = true;
    setNavigating(true);
    try {
      const data = await api<WorkspaceData>(path);
      setView(data);
      if ('events' in data) setListPage(data.page);
    } catch (error) { notify(errorMessage(error), true); }
    finally { navigationPending.current = false; setNavigating(false); }
  }, [notify]);

  const loadEvents = useCallback((page: number) => {
    if (!navigationPending.current && guard.current()) void navigate(`/api/events?page=${page}`);
  }, [navigate]);
  const openEvent = useCallback((id: string) => {
    void navigate(`/api/events/${encodeURIComponent(id)}`);
  }, [navigate]);
  const goBack = useCallback(() => loadEvents(listPage), [listPage, loadEvents]);
  useTelegramBack(event !== null, goBack);

  return {
    event, events, guard, listPage, loadEvents, openEvent, onSaved: setView,
    loading: initial.loading || navigating, error: initial.error, retry: initial.reload,
  };
}
