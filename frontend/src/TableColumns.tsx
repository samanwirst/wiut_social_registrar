import { useRef, useState } from 'react';
import { Button, Caption, Input, Section, Select } from '@telegram-apps/telegram-ui';
import { api, errorMessage } from './api';
import { Field } from './Field';
import { PollOptions } from './PollOptions';
import type { TableColumn } from './types';

export function TableColumns({ formId, columns, revision, onChanged }: {
  formId: string; columns: TableColumn[]; revision: number; onChanged: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<TableColumn | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const pending = useRef(false);
  const commit = async (next: TableColumn[]) => {
    if (pending.current) return;
    pending.current = true; setSaving(true); setError('');
    try {
      await api(`/api/forms/${encodeURIComponent(formId)}/columns`, { method: 'PUT', body: JSON.stringify({ columns: next, revision }) });
      setEditing(null); onChanged();
    } catch (failure) { setError(errorMessage(failure)); }
    finally { pending.current = false; setSaving(false); }
  };
  return <div className="table-columns">
    <Button type="button" size="s" mode="plain" aria-expanded={open} onClick={() => setOpen(value => !value)}>Columns</Button>
    {open ? <Section header="Organizer columns" footer="These values belong only to this form and follow its answer retention period. Verified student details are read-only.">
      <div className="field-stack">
        {columns.map(column => <div className="column-row" key={column.id}><span>{column.label}</span>
          <Button type="button" size="s" mode="plain" disabled={saving} onClick={() => { setEditing(structuredClone(column)); setError(''); }}>Edit</Button>
          <Button type="button" size="s" mode="plain" disabled={saving} onClick={() => {
            if (window.confirm(`Remove ${column.label} and its saved values?`)) void commit(columns.filter(item => item.id !== column.id));
          }}>Remove</Button></div>)}
        {!editing ? <Button type="button" mode="bezeled" disabled={saving || columns.length >= 20} onClick={() => { setEditing({ id: crypto.randomUUID(), label: '', type: 'text', options: [] }); setError(''); }}>Add column</Button> : null}
        {editing ? <form aria-label="Column settings" className="field-stack" onSubmit={e => {
          e.preventDefault(); void commit(columns.some(c => c.id === editing.id) ? columns.map(c => c.id === editing.id ? editing : c) : [...columns, editing]);
        }}>
          <Field label="Column name"><Input aria-label="Column name" required maxLength={100} value={editing.label} disabled={saving} onChange={e => setEditing({ ...editing, label: e.target.value })} /></Field>
          <Field label="Value type"><Select aria-label="Value type" value={editing.type} disabled={saving || columns.some(c => c.id === editing.id)} onChange={e => {
            const type = e.target.value as TableColumn['type']; setEditing({ ...editing, type, options: type === 'choice' ? ['', ''] : [] });
          }}>{[['text', 'Text'], ['number', 'Number'], ['choice', 'Choice'], ['checkbox', 'Checkbox'], ['date', 'Date']].map(([value, title]) => <option value={value} key={value}>{title}</option>)}</Select></Field>
          {editing.type === 'choice' ? <PollOptions options={editing.options} disabled={saving} locked={false} onChange={options => setEditing({ ...editing, options })} /> : null}
          <div className="actions"><Button type="submit" size="s" loading={saving} disabled={saving}>Save column</Button>
            <Button type="button" size="s" mode="plain" disabled={saving} onClick={() => setEditing(null)}>Discard</Button></div>
        </form> : null}
        {error ? <Caption className="danger" role="alert">{error}</Caption> : null}
      </div>
    </Section> : null}
  </div>;
}
