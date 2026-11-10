import { Button, Caption } from '@telegram-apps/telegram-ui';
import { useChatFile } from './hooks/useChatFile';

export function ExportParticipants({ eventId, selected, disabled = false }: { eventId: string; selected: Set<number>; disabled?: boolean }) {
  const { send, busy, notice, error } = useChatFile(eventId);
  return <div className="participant-export">
    <Button className="export-xlsx" type="button" size="s" loading={busy} disabled={busy || disabled || !selected.size}
      onClick={() => { if (selected.size) void send({ kind: 'participants', transparent: true, design_id: '', member_ids: [...selected].sort((a, b) => a - b) }); }}>Export .xlsx</Button>
    {notice ? <Caption role="status">{notice}</Caption> : null}
    {error ? <Caption role="alert" className="danger">{error}</Caption> : null}
  </div>;
}
