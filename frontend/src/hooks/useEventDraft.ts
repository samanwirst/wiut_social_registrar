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
      const { title, description, registration_open, questions, response_retention_days, revision, department } = draft;
      const updated = await api<Event>(`/api/forms/${event.id}`, { method: 'PUT', body: JSON.stringify({
        title, description, registration_open, questions, response_retention_days, revision, department,
      }) });
      const next = { ...updated, link: event.link, qr_styling_enabled: event.qr_styling_enabled };
      onSaved(next);
      setDraft(structuredClone(next));
      setDirty(false);
      notify('Form updated');
      if (supports('6.1')) telegram?.HapticFeedback?.notificationOccurred('success');
    } catch (error) { notify(errorMessage(error), true); }
    finally { savingRef.current = false; setSaving(false); }
  };
  return { draft, dirty, saving, change, save };
}
