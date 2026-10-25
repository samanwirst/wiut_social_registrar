import { useRef, useState } from 'react';
import { api, errorMessage } from '../api';
import type { CellChange, CellValue, Member, Question, TableColumn } from '../types';

export const CELL_TEXT_LIMIT = 2000;
export interface CellEditorProps {
  formId: string; member: Member; definition: Question | TableColumn; scope: 'answer' | 'column';
  columnsRevision: number; onSaved: (id: number, change: CellChange) => void;
}

export function useCellEditor({ formId, member, definition, scope, columnsRevision, onSaved }: CellEditorProps, initialDraft?: CellValue) {
  const value: CellValue = (scope === 'answer' ? member.answers?.[definition.id] : member.organizer_values[definition.id]) ?? null;
  const [draft, setDraft] = useState<CellValue>(() => initialDraft ?? value);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const pending = useRef(false);
  const expired = Date.parse(member.editable_until) <= Date.now();
  const save = async () => {
    if (pending.current || expired) return false;
    pending.current = true; setSaving(true); setError('');
    try {
      const result = await api<CellChange>(`/api/forms/${encodeURIComponent(formId)}/members/${member.telegram_id}`, {
        method: 'PATCH', body: JSON.stringify({ scope, field: definition.id, value: draft, revision: member.row_revision, columns_revision: columnsRevision }),
      });
      onSaved(member.telegram_id, result);
      return true;
    } catch (failure) { setError(errorMessage(failure)); return false; }
    finally { pending.current = false; setSaving(false); }
  };
  return { value, draft, setDraft, saving, pending, error, setError, expired, save };
}
