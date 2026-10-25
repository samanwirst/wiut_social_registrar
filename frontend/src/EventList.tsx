import { Caption, Cell, List, Placeholder, Section, Title } from '@telegram-apps/telegram-ui';
import { Pagination } from './Pagination';
import type { EventsPage } from './types';
import { Chevron } from './Icons';

export function EventList({ data, onOpen, onPage, busy }: {
  data: EventsPage; onOpen: (id: string) => void; onPage: (page: number) => void; busy: boolean;
}) {
  return <>
    <div className="page-heading"><Title level="1" Component="h1">Your forms</Title>
      <Caption className="muted">Events, advisor applications, and more</Caption></div>
    <List className="section-list">
      <Section className="studio-section events-section" header={`${data.total} forms`}>
        {data.forms.length ? data.forms.map(event => <Cell key={event.id} Component="button" type="button"
          className="event-card" disabled={busy} onClick={() => onOpen(event.id)} multiline
          subtitle={event.description || undefined}
          description={<span className="event-meta">{event.department && <>{event.department}<br /></>}{event.members} {event.members === 1 ? 'person' : 'people'}
            {event.questions.length ? ` · ${event.questions.length} ${event.questions.length === 1 ? 'question' : 'questions'}` : ''}</span>}
          after={<div className="event-trailing"><span className={`event-status${event.registration_open ? '' : ' closed'}`}>
            {event.registration_open ? 'Open' : 'Closed'}</span><Chevron /></div>}>{event.title}</Cell>)
          : <Placeholder header="Your first form awaits" description="Create a form in the bot, then return here to configure it" />}
      </Section>
      <Section.Footer className="event-help">Create a form with <code>/new_form [form name]</code> in the bot</Section.Footer>
    </List>
    <Pagination {...data} onPage={onPage} disabled={busy} />
  </>;
}
