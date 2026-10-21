import { useEffect, useState } from 'react';
import { Button, Caption, Placeholder, Section, Spinner } from '@telegram-apps/telegram-ui';
import { api, errorMessage } from './api';
import { Pagination } from './Pagination';
import type { MembersPage } from './types';

function Contact({ value, prefix }: { value: string | null; prefix: string }) {
  return value ? <a href={prefix + value} target="_blank" rel="noopener noreferrer">{value}</a> : <>—</>;
}

export function Participants({ eventId }: { eventId: string }) {
  const [data, setData] = useState<MembersPage | null>(null);
  const [page, setPage] = useState(0);
  const [refresh, setRefresh] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setError('');
    api<MembersPage>(`/api/events/${eventId}/members?page=${page}`, { signal: controller.signal })
      .then(result => { if (!controller.signal.aborted) setData(result); })
      .catch(error => { if (!controller.signal.aborted) setError(errorMessage(error)); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [eventId, page, refresh]);

  return <Section className="participants" header="Participants" footer="Additional answers expire automatically. A dash means no answer is available.">
    <div className="table-tools">
      <Caption>{data?.total ?? '…'} participants · 10 per page</Caption>
      <div className="actions">
        <Button type="button" size="s" mode="bezeled" disabled={loading} onClick={() => setRefresh(value => value + 1)}>Refresh</Button>
      </div>
    </div>
    {error ? <Placeholder header="Couldn't load participants" description={error} action={
      <Button type="button" mode="bezeled" onClick={() => setRefresh(value => value + 1)}>Try again</Button>} />
      : loading ? <div className="loading" role="status"><Spinner size="m" /><span>Loading participants…</span></div>
      : data && data.members.length ? <div className="scroll-table" tabIndex={0} role="region" aria-label="Participant contacts and answers">
        <table><thead><tr>{['Student ID', 'Name', 'Telegram', 'Email', 'Phone', 'Level', ...data.questions.map(q => q.label)]
          .map((label, index) => <th scope="col" key={index}>{label}</th>)}</tr></thead>
          <tbody>{data.members.map(member => <tr key={member.telegram_id}>
            <td>{member.student_id}</td><td>{member.name}</td>
            <td>{member.telegram_username ? <a href={`https://t.me/${member.telegram_username}`} target="_blank" rel="noopener noreferrer">@{member.telegram_username}</a>
              : <a href={`tg://user?id=${member.telegram_id}`}>Open profile</a>}</td>
            <td><Contact value={member.email} prefix="mailto:" /></td>
            <td><Contact value={member.phone_number} prefix="tel:" /></td><td>{member.education_level || '—'}</td>
            {data.questions.map(q => {
              const value = member.answers?.[q.id];
              return <td key={q.id} title={member.answers_expires_at ? `Answers expire ${new Date(member.answers_expires_at).toLocaleString()}` : undefined}>
                {Array.isArray(value) ? value.join(', ') : value || '—'}</td>;
            })}
          </tr>)}</tbody></table>
      </div> : <Placeholder header="The guest list starts here" description="Share the event QR code to invite your first participant." />}
    {data ? <Pagination {...data} disabled={loading} onPage={setPage} /> : null}
  </Section>;
}
