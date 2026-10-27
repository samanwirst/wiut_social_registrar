import { useCallback, useEffect, useRef, useState } from 'react';
import type { MutableRefObject } from 'react';
import { Button, Caption, Checkbox, Placeholder, Section, Spinner } from '@telegram-apps/telegram-ui';
import { api, errorMessage } from './api';
import { EditableCell } from './EditableCell';
import { TableColumns } from './TableColumns';
import { Broadcasts } from './Broadcasts';
import { AnswerDetails } from './AnswerDetails';
import { openTelegramChat } from './telegram';
import { useRemoteResource } from './hooks/useRemoteResource';
import { Pagination } from './Pagination';
import { ExportParticipants } from './ExportParticipants';
import type { Broadcast, CellChange, MembersPage } from './types';

function Contact({ value, prefix }: { value: string | null; prefix: string }) {
  return value ? <a href={prefix + value} target="_blank" rel="noopener noreferrer">{value}</a> : <>—</>;
}

export function Participants({ eventId, detailBack, onDirtyChange }: { eventId: string; detailBack: MutableRefObject<(() => void) | null>; onDirtyChange: (dirty: boolean) => void }) {
  const [page, setPage] = useState(0);
  const [selected, setSelected] = useState<Set<number>>(() => new Set());
  const [preparing, setPreparing] = useState(false);
  const [composeError, setComposeError] = useState('');
  const [detail, setDetail] = useState<{ memberId: number; fieldId: string; scope: 'answer' | 'column'; initialDraft?: string } | null>(null);
  const detailOpener = useRef<HTMLTableCellElement | null>(null);
  const closeDetail = useCallback(() => setDetail(null), []);
  const openDetail = (memberId: number, fieldId: string, scope: 'answer' | 'column', initialDraft?: string) => {
    detailOpener.current = document.activeElement?.closest<HTMLTableCellElement>('td') ?? null;
    setDetail({ memberId, fieldId, scope, initialDraft });
  };
  useEffect(() => {
    if (!detail) detailOpener.current?.querySelector<HTMLButtonElement>('.cell-value')?.focus({ preventScroll: true });
  }, [detail]);
  const request = useRef({ id: crypto.randomUUID(), audience: '' });
  const pending = useRef(false);
  const load = useCallback((signal: AbortSignal) =>
    api<MembersPage>(`/api/forms/${encodeURIComponent(eventId)}/members?page=${page}`, { signal }), [eventId, page]);
  const { data, loading, error, reload, update } = useRemoteResource(load);
  const changeSelection = (next: Set<number>) => { setSelected(next); setComposeError(''); };
  const prepare = async () => {
    if (pending.current || selected.size === 0) return;
    const ids = [...selected].sort((a, b) => a - b);
    const audience = ids.join(',');
    if (request.current.audience !== audience) request.current = { id: crypto.randomUUID(), audience };
    pending.current = true; setPreparing(true); setComposeError('');
    try {
      const result = await api<Broadcast>(`/api/forms/${encodeURIComponent(eventId)}/broadcasts`, {
        method: 'POST', body: JSON.stringify({ recipient_ids: ids, request_id: request.current.id }),
      });
      openTelegramChat(result.compose_url);
    } catch (failure) { setComposeError(errorMessage(failure)); }
    finally { pending.current = false; setPreparing(false); }
  };
  const cellSaved = (id: number, change: CellChange) => update(previous => previous ? ({ ...previous,
    members: previous.members.map(member => member.telegram_id !== id ? member : ({ ...member, row_revision: change.revision,
      ...(change.scope === 'answer' ? { answers: { ...member.answers, [change.field]: change.value as string | string[] } }
        : { organizer_values: { ...member.organizer_values, [change.field]: change.value } }),
    })),
  }) : previous);
  const allPage = Boolean(data?.members.length && data.members.every(member => selected.has(member.telegram_id)));
  const detailMember = data?.members.find(member => member.telegram_id === detail?.memberId);
  const detailField = detail && (detail.scope === 'answer' ? data?.questions : data?.columns)?.find(field => field.id === detail.fieldId);

  return <><Section className="studio-section participants" header="People" footer="Tap answers or custom values to view or edit">
    <div className="table-tools">
      <Caption>{data?.total ?? '…'} people · 10 per page</Caption>
      <div className="actions">
        <ExportParticipants key={eventId} eventId={eventId} />
        <Button type="button" size="s" mode="bezeled" disabled={loading} onClick={reload}>Refresh</Button>
      </div>
    </div>
    {data ? <TableColumns formId={eventId} columns={data.columns} revision={data.columns_revision} onChanged={reload} /> : null}
    <div className="audience-tools">
      <Caption role="status">{selected.size} selected{selected.size ? ' across pages' : ''}</Caption>
      <div className="actions"><Button type="button" size="s" mode="bezeled" disabled={!selected.size || preparing} loading={preparing} onClick={() => { void prepare(); }}>Prepare message</Button>
        {selected.size ? <Button type="button" size="s" mode="plain" disabled={preparing} onClick={() => changeSelection(new Set())}>Clear selection</Button> : null}</div>
      {composeError ? <Caption role="alert" className="danger">{composeError}</Caption> : null}
    </div>
    {error ? <Placeholder header="Couldn't load people" description={error} action={
      <Button type="button" mode="bezeled" onClick={reload}>Try again</Button>} />
      : loading ? <div className="loading" role="status"><Spinner size="m" /><span>Loading participants…</span></div>
      : data && data.members.length ? <div className="scroll-table" tabIndex={0} role="region" aria-label="Participant contacts and answers">
        <table><thead><tr><th scope="col" className="selection-cell"><Checkbox aria-label="Select this page" checked={allPage} indeterminate={!allPage && data.members.some(member => selected.has(member.telegram_id))} disabled={preparing} onChange={e => {
          const next = new Set(selected); data.members.forEach(member => { if (e.target.checked) next.add(member.telegram_id); else next.delete(member.telegram_id); }); changeSelection(next);
        }} /></th>{['Student ID', 'Name', 'Telegram', 'Email', 'Phone', 'Level', ...data.questions.map(q => q.label), ...data.columns.map(c => c.label)]
          .map((label, index) => <th scope="col" key={index}>{label}</th>)}</tr></thead>
          <tbody>{data.members.map(member => <tr key={member.telegram_id}>
            <td className="selection-cell"><Checkbox aria-label={`Select ${member.name || member.student_id}`} checked={selected.has(member.telegram_id)} disabled={preparing} onChange={e => {
              const next = new Set(selected); if (e.target.checked) next.add(member.telegram_id); else next.delete(member.telegram_id); changeSelection(next);
            }} /></td>
            <td>{member.student_id}</td><td>{member.name}</td>
            <td>{member.telegram_username ? <a href={`https://t.me/${member.telegram_username}`} target="_blank" rel="noopener noreferrer">@{member.telegram_username}</a>
              : <a href={`tg://user?id=${member.telegram_id}`}>Open profile</a>}</td>
            <td><Contact value={member.email} prefix="mailto:" /></td>
            <td><Contact value={member.phone_number} prefix="tel:" /></td><td>{member.education_level || '—'}</td>
            {data.questions.map(q => <EditableCell key={q.id} formId={eventId} member={member} definition={q} scope="answer" columnsRevision={data.columns_revision} onSaved={cellSaved}
              onExpand={initialDraft => openDetail(member.telegram_id, q.id, 'answer', initialDraft)} />)}
            {data.columns.map(c => <EditableCell key={c.id} formId={eventId} member={member} definition={c} scope="column" columnsRevision={data.columns_revision} onSaved={cellSaved}
              onExpand={initialDraft => openDetail(member.telegram_id, c.id, 'column', initialDraft)} />)}
          </tr>)}</tbody></table>
      </div> : <Placeholder header="No responses yet" description="Share the form's QR code or link to invite people" />}
    {data ? <Pagination {...data} disabled={loading} onPage={setPage} /> : null}
  </Section>
    <Broadcasts formId={eventId} />
    {detail && detailMember && detailField && data ? <AnswerDetails key={`${detail.memberId}:${detail.fieldId}:${detail.scope}`} formId={eventId}
      member={detailMember} definition={detailField} scope={detail.scope} columnsRevision={data.columns_revision} onSaved={cellSaved}
      initialDraft={detail.initialDraft} back={detailBack} onClose={closeDetail} onDirtyChange={onDirtyChange} /> : null}
  </>;
}
