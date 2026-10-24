import { useState } from 'react';
import type { MutableRefObject } from 'react';
import { Button, Caption, Cell, Input, List, Section, Switch, TabsList, Textarea, Title } from '@telegram-apps/telegram-ui';
import { useEventDraft } from './hooks/useEventDraft';
import { Questions } from './Questions';
import { Field } from './Field';
import { Participants } from './Participants';
import { EventShare } from './EventShare';
import type { EventDetails, Notify } from './types';

type Tab = 'overview' | 'questions' | 'participants' | 'qr';
const tabs = ['overview', 'questions', 'participants', 'qr'] as const;

export function EventEditor({ event, guard, notify, onSaved }: {
  event: EventDetails; guard: MutableRefObject<() => boolean>; notify: Notify; onSaved: (event: EventDetails) => void;
}) {
  const [tab, setTab] = useState<Tab>('overview');
  const { draft, dirty, saving, change, save } = useEventDraft(event, guard, onSaved, notify);

  return <>
    <div className="page-heading"><Title level="1" Component="h1">{event.title}</Title>
      <Caption className="muted">{event.registration_open ? 'Registration open' : 'Registration closed'}</Caption></div>
    <TabsList className="tabs" aria-label="Event sections" onKeyDown={e => {
      if (saving || !['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(e.key)) return;
      e.preventDefault();
      const index = e.key === 'Home' ? 0 : e.key === 'End' ? tabs.length - 1
        : (tabs.indexOf(tab) + (e.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length;
      setTab(tabs[index]);
      e.currentTarget.querySelectorAll<HTMLButtonElement>('[role=tab]')[index]?.focus();
    }}>{tabs.map(value =>
      <TabsList.Item key={value} id={`event-tab-${value}`} type="button" selected={tab === value} aria-selected={tab === value}
        aria-controls="event-content" tabIndex={tab === value ? 0 : -1} disabled={saving} onClick={() => setTab(value)}>
        {value === 'qr' ? 'QR' : value[0].toUpperCase() + value.slice(1)}</TabsList.Item>)}</TabsList>
    <div id="event-content" role="tabpanel" aria-labelledby={`event-tab-${tab}`}>
    {tab === 'participants' ? <Participants eventId={event.id} />
      : tab === 'qr' ? <EventShare event={event} notify={notify} />
      : <form className="event-form" onSubmit={save} aria-label="Event settings">
        {tab === 'overview' ? <List className="section-list editor-fields">
          <Section className="studio-section" header="Event details">
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
    </div>
  </>;
}
