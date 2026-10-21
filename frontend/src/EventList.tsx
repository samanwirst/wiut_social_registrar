import { Caption, Cell, List, Placeholder, Section, Title } from '@telegram-apps/telegram-ui';
import { Pagination } from './Pagination';
import type { EventsPage } from './types';

export function EventList({ data, onOpen, onPage, busy }: {
  data: EventsPage; onOpen: (id: string) => void; onPage: (page: number) => void; busy: boolean;
}) {
  return <>
    <div className="page-heading"><Title level="1" Component="h1">Your events</Title>
      <Caption className="muted">Manage registration and participants.</Caption></div>
    <List className="section-list">
      <Section className="events-section" header={`${data.total} events`}>
        {data.events.length ? data.events.map(event => <Cell key={event.id} Component="button" type="button"
          className="event-card" disabled={busy} onClick={() => onOpen(event.id)} multiline
          subtitle={event.description || undefined}
          description={<span className="event-meta">{event.members} {event.members === 1 ? 'participant' : 'participants'}
            {event.questions.length ? ` · ${event.questions.length} ${event.questions.length === 1 ? 'question' : 'questions'}` : ''}</span>}
          after={<div className="event-trailing"><span className={`event-status${event.registration_open ? '' : ' closed'}`}>
            {event.registration_open ? 'Open' : 'Closed'}</span><span className="event-chevron" aria-hidden="true">›</span></div>}>{event.title}</Cell>)
          : <Placeholder header="Your first event awaits" description="Create an event in the bot, then return here to configure it." />}
      </Section>
      <Section.Footer className="event-help">Create an event with <code>/new_event Event name</code> in the bot.</Section.Footer>
    </List>
    <Pagination {...data} onPage={onPage} disabled={busy} />
  </>;
}
