import { useEffect, useRef, useState } from 'react';
import { Button, Caption } from '@telegram-apps/telegram-ui';
import { errorMessage, exportParticipants } from './api';
import { useObjectUrl } from './hooks/useRemoteResource';

export function ExportParticipants({ eventId }: { eventId: string }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [blob, setBlob] = useState<Blob | null>(null);
  const controller = useRef<AbortController | null>(null);
  const url = useObjectUrl(blob);
  const anchor = useRef<HTMLAnchorElement>(null);
  useEffect(() => () => controller.current?.abort(), []);
  useEffect(() => { if (url) anchor.current?.click(); }, [url]);
  const download = async () => {
    if (controller.current) return;
    const next = new AbortController();
    controller.current = next;
    setBusy(true); setError(''); setBlob(null);
    try {
      const result = await exportParticipants(eventId, next.signal);
      if (!next.signal.aborted) setBlob(result);
    } catch (failure) {
      if (!next.signal.aborted) setError(errorMessage(failure));
    } finally {
      if (!next.signal.aborted) { controller.current = null; setBusy(false); }
    }
  };
  return <div className="participant-export">
    <Button className="export-xlsx" type="button" size="s" loading={busy} disabled={busy}
      onClick={() => { void download(); }}>Export .xlsx</Button>
    <a ref={anchor} href={url || undefined} download={`participants-${eventId}.xlsx`} hidden />
    {error ? <Caption role="alert" className="danger">{error}</Caption> : null}
  </div>;
}
