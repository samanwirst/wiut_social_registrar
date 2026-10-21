import { useRef, useState } from 'react';
import type { FormEvent, MutableRefObject } from 'react';
import { api, errorMessage } from '../api';
import { supports, telegram } from '../telegram';
import type { Event, EventDetails, Notify } from '../types';
import { useUnsavedChanges } from './useUnsavedChanges';

export function useEventDraft(event: EventDetails, guard: MutableRefObject<() => boolean>, onSaved: (event: EventDetails) => void, notify: Notify) {
  const [draft, setDraft] = useState(() => structuredClone(event));
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const savingRef = useRef(false);
  useUnsavedChanges(dirty, savingRef, guard);

  const change = (value: Partial<EventDetails>) => {
    setDraft(previous => ({ ...previous, ...value }));
    setDirty(true);
  };
  const save = async (submission: FormEvent) => {
    submission.preventDefault();
    if (savingRef.current || !dirty) return;
    savingRef.current = true;
    setSaving(true);
    try {
      const { title, description, registration_open, questions, response_retention_days, revision } = draft;
      const updated = await api<Event>(`/api/events/${event.id}`, { method: 'PUT', body: JSON.stringify({
        title, description, registration_open, questions, response_retention_days, revision,
      }) });
      const next = { ...updated, link: event.link };
      onSaved(next);
      setDraft(structuredClone(next));
      setDirty(false);
      notify('Event updated.');
      if (supports('6.1')) telegram?.HapticFeedback?.notificationOccurred('success');
    } catch (error) { notify(errorMessage(error), true); }
    finally { savingRef.current = false; setSaving(false); }
  };
  return { draft, dirty, saving, change, save };
}
