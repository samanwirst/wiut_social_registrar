import { useEffect, useRef, useState } from 'react';
import type { FormEvent, MutableRefObject } from 'react';
import { Button, Caption, Cell, Input, List, Section, Switch, TabsList, Textarea, Title } from '@telegram-apps/telegram-ui';
import { api, errorMessage } from './api';
import { Questions } from './Questions';
import { Field } from './Field';
import { Participants } from './Participants';
import { EventShare } from './EventShare';
import { supports, telegram } from './telegram';
import type { Event, EventDetails, Notify } from './types';

type Tab = 'overview' | 'questions' | 'participants' | 'qr';

export function EventEditor({ event, guard, notify, onSaved }: {
  event: EventDetails; guard: MutableRefObject<() => boolean>; notify: Notify; onSaved: (event: EventDetails) => void;
}) {
  const [draft, setDraft] = useState(() => structuredClone(event));
  const [tab, setTab] = useState<Tab>('overview');
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const savingRef = useRef(false);

  useEffect(() => {
    guard.current = () => !savingRef.current && (!dirty || window.confirm('Discard your unsaved event changes?'));
    if (supports('6.2')) {
      if (dirty) telegram?.enableClosingConfirmation(); else telegram?.disableClosingConfirmation();
    }
    const beforeUnload = (e: BeforeUnloadEvent) => { if (dirty || savingRef.current) { e.preventDefault(); e.returnValue = ''; } };
    window.addEventListener('beforeunload', beforeUnload);
    return () => {
      guard.current = () => true;
      window.removeEventListener('beforeunload', beforeUnload);
      if (supports('6.2')) telegram?.disableClosingConfirmation();
    };
  }, [dirty, guard]);

  const change = (value: Partial<EventDetails>) => { setDraft(previous => ({ ...previous, ...value })); setDirty(true); };
  const save = async (e: FormEvent) => {
    e.preventDefault();
    if (savingRef.current || !dirty) return;
    savingRef.current = true; setSaving(true);
    try {
      const { title, description, registration_open, questions, response_retention_days, revision } = draft;
      const updated = await api<Event>(`/api/events/${event.id}`, { method: 'PUT', body: JSON.stringify({
        title, description, registration_open, questions, response_retention_days, revision,
      }) });
      const next = { ...updated, link: event.link };
      onSaved(next); setDraft(structuredClone(next)); setDirty(false);
      notify('Event updated.');
      if (supports('6.1')) telegram?.HapticFeedback?.notificationOccurred('success');
    } catch (error) { notify(errorMessage(error), true); }
    finally { savingRef.current = false; setSaving(false); }
  };

  return <>
    <div className="page-heading"><Title level="1" Component="h1">{event.title}</Title>
      <Caption className="muted">{event.registration_open ? 'Registration open' : 'Registration closed'}</Caption></div>
    <TabsList className="tabs" aria-label="Event sections">{(['overview', 'questions', 'participants', 'qr'] as const).map(value =>
      <TabsList.Item key={value} type="button" selected={tab === value} aria-selected={tab === value} disabled={saving} onClick={() => setTab(value)}>
        {value === 'qr' ? 'QR' : value[0].toUpperCase() + value.slice(1)}</TabsList.Item>)}</TabsList>
    {tab === 'participants' ? <Participants eventId={event.id} />
      : tab === 'qr' ? <EventShare event={event} notify={notify} />
      : <form className="event-form" onSubmit={save} aria-label="Event settings">
        {tab === 'overview' ? <List className="section-list editor-fields">
          <Section header="Event details">
            <div className="field-stack">
              <Field label="Event name"><Input aria-label="Event name" value={draft.title} maxLength={200} required disabled={saving}
                onChange={e => change({ title: e.target.value })} /></Field>
              <Field label="Description"><Textarea aria-label="Description" value={draft.description} maxLength={4000} rows={4} disabled={saving}
                placeholder="What should your participants know?" onChange={e => change({ description: e.target.value })} /></Field>
            </div>
            <Cell Component="label" multiline subtitle="Turn this off to close the event to new participants."
              after={<Switch aria-label="Accept registrations" checked={draft.registration_open} disabled={saving}
                onChange={e => change({ registration_open: e.target.checked })} />}>Accept registrations</Cell>
          </Section>
        </List> : <Questions questions={draft.questions} locked={event.form_locked} disabled={saving} onChange={questions => change({ questions })} />}
        <div className="savebar">
          <Caption id="save-status" className="muted" role="status">{dirty ? 'You have unsaved changes' : 'All changes saved'}</Caption>
          <Button type="submit" size="s" id="save-event" loading={saving} disabled={saving || !dirty}>Save changes</Button>
        </div>
      </form>}
  </>;
}
