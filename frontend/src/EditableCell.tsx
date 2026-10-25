import { useRef, useState } from 'react';
import { Caption, Checkbox, IconButton, Input, Select, Spinner, Textarea } from '@telegram-apps/telegram-ui';
import { api, errorMessage } from './api';
import { CheckIcon, CloseIcon } from './Icons';
import type { CellChange, CellValue, Member, Question, TableColumn } from './types';

export function EditableCell({ formId, member, definition, scope, columnsRevision, onSaved }: {
  formId: string; member: Member; definition: Question | TableColumn; scope: 'answer' | 'column';
  columnsRevision: number; onSaved: (id: number, change: CellChange) => void;
}) {
  const value: CellValue = (scope === 'answer' ? member.answers?.[definition.id] : member.organizer_values[definition.id]) ?? null;
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<CellValue>(value);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const pending = useRef(false);
  const expired = Date.parse(member.editable_until) <= Date.now();
  const display = Array.isArray(value) ? value.join(', ') : typeof value === 'boolean' ? value ? 'Yes' : 'No' : value || '—';
  const save = async () => {
    if (pending.current) return;
    pending.current = true; setSaving(true); setError('');
    try {
      const result = await api<CellChange>(`/api/forms/${encodeURIComponent(formId)}/members/${member.telegram_id}`, {
        method: 'PATCH', body: JSON.stringify({ scope, field: definition.id, value: draft, revision: member.row_revision, columns_revision: columnsRevision }),
      });
      onSaved(member.telegram_id, result); setEditing(false);
    } catch (failure) { setError(errorMessage(failure)); }
    finally { pending.current = false; setSaving(false); }
  };
  const label = `${definition.label} for ${member.name || member.student_id}`;
  return <td className={`editable-cell${editing ? ' cell-editing' : ''}`}>
    {editing ? <form className="cell-editor" aria-label={`Edit ${label}`} onSubmit={e => { e.preventDefault(); void save(); }} onKeyDown={e => {
      if (e.key === 'Escape' && !saving) setEditing(false);
    }}>
      <div className="cell-input">{definition.type === 'checkbox' ? <div className="cell-check"><Checkbox aria-label={label} checked={draft === true} disabled={saving} onChange={e => setDraft(e.target.checked)} /></div>
        : definition.type === 'choice' || definition.type === 'single_choice' || definition.type === 'multiple_choice' ? <Select aria-label={label}
            value={Array.isArray(draft) ? draft.length === 1 ? draft[0] : '' : typeof draft === 'string' ? draft : ''}
            disabled={saving} onChange={e => setDraft(definition.type === 'multiple_choice' ? e.target.value ? [e.target.value] : [] : e.target.value)}>
            <option value="">Choose an option</option>{definition.options.map(option => <option key={option}>{option}</option>)}</Select>
            : definition.type === 'number' || definition.type === 'date' ? <Input autoFocus aria-label={label} type={definition.type} step={definition.type === 'number' ? 'any' : undefined} value={typeof draft === 'string' ? draft : ''} disabled={saving} onChange={e => setDraft(e.target.value)} />
              : <Textarea autoFocus aria-label={label} rows={1} maxLength={2000} value={typeof draft === 'string' ? draft : ''} disabled={saving} onChange={e => setDraft(e.target.value)} />}</div>
      <div className="cell-actions">
        <IconButton type="submit" className="cell-action" size="s" mode="bezeled" aria-label="Save" title="Save" aria-busy={saving} disabled={saving}>
          {saving ? <Spinner size="s" /> : <CheckIcon />}
        </IconButton>
        <IconButton type="button" className="cell-action cell-dismiss" size="s" mode="plain" aria-label="Discard" title="Discard" disabled={saving} onClick={() => setEditing(false)}><CloseIcon /></IconButton>
      </div>
      {error ? <Caption role="alert" className="danger cell-error">{error}</Caption> : null}
    </form> : <button type="button" className="cell-value" disabled={expired} aria-label={`Edit ${label}`} title={expired ? 'Editing is no longer available' : 'Edit this cell'} onClick={() => { setDraft(value); setError(''); setEditing(true); }}>{display}</button>}
  </td>;
}
