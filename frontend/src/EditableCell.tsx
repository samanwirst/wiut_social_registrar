import { useState } from 'react';
import { Caption, Checkbox, IconButton, Input, Select, Spinner, Textarea } from '@telegram-apps/telegram-ui';
import { CheckIcon, CloseIcon, ExpandIcon } from './Icons';
import { CELL_TEXT_LIMIT, useCellEditor } from './hooks/useCellEditor';
import type { CellEditorProps } from './hooks/useCellEditor';
import { useTextOverflow } from './hooks/useTextOverflow';

export function EditableCell({ onExpand, ...props }: CellEditorProps & { onExpand: (initialDraft?: string) => void }) {
  const { member, definition } = props;
  const { value, draft, setDraft, saving, error, setError, expired, save } = useCellEditor(props);
  const [editing, setEditing] = useState(false);
  const display = Array.isArray(value) ? value.join(', ') : typeof value === 'boolean' ? value ? 'Yes' : 'No' : value || '—';
  const { ref, overflowing } = useTextOverflow(display);
  const longText = definition.type === 'text' && overflowing;
  const label = `${definition.label} for ${member.name || member.student_id}`;
  return <td className={`editable-cell${editing ? ' cell-editing' : ''}`}>
    {editing ? <form className="cell-editor" aria-label={`Edit ${label}`} onSubmit={async e => { e.preventDefault(); if (await save()) setEditing(false); }} onKeyDown={e => {
      if (e.key === 'Escape' && !saving) setEditing(false);
    }}>
      <div className="cell-input">{definition.type === 'checkbox' ? <div className="cell-check"><Checkbox aria-label={label} checked={draft === true} disabled={saving} onChange={e => setDraft(e.target.checked)} /></div>
        : definition.type === 'choice' || definition.type === 'single_choice' || definition.type === 'multiple_choice' ? <Select aria-label={label}
            value={Array.isArray(draft) ? draft.length === 1 ? draft[0] : '' : typeof draft === 'string' ? draft : ''}
            disabled={saving} onChange={e => setDraft(definition.type === 'multiple_choice' ? e.target.value ? [e.target.value] : [] : e.target.value)}>
            <option value="">Choose an option</option>{definition.options.map(option => <option key={option}>{option}</option>)}</Select>
            : definition.type === 'number' || definition.type === 'date' ? <Input autoFocus aria-label={label} type={definition.type} step={definition.type === 'number' ? 'any' : undefined} value={typeof draft === 'string' ? draft : ''} disabled={saving} onChange={e => setDraft(e.target.value)} />
              : <Textarea autoFocus aria-label={label} rows={1} maxLength={CELL_TEXT_LIMIT} value={typeof draft === 'string' ? draft : ''} disabled={saving} onChange={e => setDraft(e.target.value)} />}</div>
      <div className="cell-actions">
        <IconButton type="submit" className="cell-action" size="s" mode="bezeled" aria-label="Save" title="Save" aria-busy={saving} disabled={saving}>
          {saving ? <Spinner size="s" /> : <CheckIcon />}
        </IconButton>
        <IconButton type="button" className="cell-action cell-dismiss" size="s" mode="plain" aria-label="Discard" title="Discard" disabled={saving} onClick={() => setEditing(false)}><CloseIcon /></IconButton>
      </div>
      {definition.type === 'text' ? <IconButton type="button" className="cell-action cell-expand" size="s" mode="plain" aria-label="Expand editor" title="Expand editor" disabled={saving}
        onClick={() => { onExpand(typeof draft === 'string' ? draft : ''); setEditing(false); }}><ExpandIcon /></IconButton> : null}
      {error ? <Caption role="alert" className="danger cell-error">{error}</Caption> : null}
    </form> : <button type="button" className="cell-value" disabled={expired && !longText} aria-label={`${longText ? 'Read' : 'Edit'} ${label}`} title={longText ? 'Read full answer' : expired ? 'Editing is no longer available' : 'Edit this cell'}
      onClick={() => { if (longText) onExpand(); else { setDraft(value); setError(''); setEditing(true); } }}>
      <span ref={definition.type === 'text' ? ref : undefined} className={definition.type === 'text' ? 'cell-preview' : undefined}>{display}</span>
      {longText ? <span className="cell-read-more">Read more</span> : null}
    </button>}
  </td>;
}
