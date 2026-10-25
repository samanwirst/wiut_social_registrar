import { useCallback, useEffect, useId, useState } from 'react';
import type { CSSProperties, MutableRefObject } from 'react';
import { Button, Caption, IconButton, Modal, Textarea } from '@telegram-apps/telegram-ui';
import { CloseIcon } from './Icons';
import { CELL_TEXT_LIMIT, useCellEditor } from './hooks/useCellEditor';
import type { CellEditorProps } from './hooks/useCellEditor';
import { useVisualViewport } from './hooks/useVisualViewport';

export function AnswerDetails({ back, onClose, onDirtyChange, initialDraft, ...props }: CellEditorProps & {
  back: MutableRefObject<(() => void) | null>; onClose: () => void; onDirtyChange: (dirty: boolean) => void; initialDraft?: string;
}) {
  const { value, draft, setDraft, saving, pending, error, setError, expired, save } = useCellEditor(props, initialDraft);
  const [editing, setEditing] = useState(initialDraft !== undefined);
  const dirty = editing && (draft ?? '') !== (value ?? '');
  const titleId = useId(), personId = useId();
  const size = useVisualViewport();
  const close = useCallback(() => {
    if (pending.current || dirty && !window.confirm('Discard your unsaved answer changes?')) return;
    onClose();
  }, [dirty, pending, onClose]);
  useEffect(() => {
    back.current = close;
    return () => { if (back.current === close) back.current = null; };
  }, [back, close]);
  useEffect(() => {
    onDirtyChange(dirty);
    return () => onDirtyChange(false);
  }, [dirty, onDirtyChange]);
  return <Modal open onOpenChange={open => { if (!open) close(); }} dismissible={!saving && !dirty}
    className="answer-panel" aria-labelledby={titleId} aria-describedby={personId}
    style={{ '--answer-viewport-height': `${size.height}px`, '--answer-viewport-top': `${size.top}px` } as CSSProperties}
    onKeyDown={event => { if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); close(); } }}>
    <div className="answer-header"><span>{props.scope === 'answer' ? 'Answer' : 'Value'}</span>
      <IconButton type="button" mode="plain" size="s" aria-label="Close answer" disabled={saving} onClick={close}><CloseIcon /></IconButton></div>
    <div className="answer-content" data-vaul-no-drag>
      <Caption id={personId} className="muted">{props.member.name} · {props.member.student_id}</Caption>
      <h2 id={titleId}>{props.definition.label}</h2>
      {editing ? <form id="answer-editor" aria-label="Edit full answer" onSubmit={async event => {
        event.preventDefault(); if (await save()) setEditing(false);
      }}><div className="answer-input"><Textarea autoFocus aria-label={props.definition.label} rows={10} maxLength={CELL_TEXT_LIMIT}
        disabled={saving} value={typeof draft === 'string' ? draft : ''} onChange={event => setDraft(event.target.value)} />
        </div>
        {error ? <Caption role="alert" className="danger">{error}</Caption> : null}
      </form> : <div className="answer-text">{typeof value === 'string' && value ? value : '—'}</div>}
    </div>
    {/* Separate buttons prevent the Edit click from activating a newly rendered submit action. */}
    {!expired ? <div className="answer-actions">{editing
      ? <Button key="save" type="submit" form="answer-editor" loading={saving} disabled={saving}>Save</Button>
      : <Button key="edit" type="button" mode="bezeled" onClick={() => { setDraft(value); setError(''); setEditing(true); }}>Edit</Button>}
    </div> : null}
  </Modal>;
}
