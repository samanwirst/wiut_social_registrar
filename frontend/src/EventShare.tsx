import { useCallback } from 'react';
import { Button, Caption, Section, Spinner } from '@telegram-apps/telegram-ui';
import { eventQr } from './api';
import { useObjectUrl, useRemoteResource } from './hooks/useRemoteResource';
import type { EventDetails, Notify } from './types';

export function EventShare({ event, notify }: { event: EventDetails; notify: Notify }) {
  const load = useCallback((signal: AbortSignal) => eventQr(event.id, signal), [event.id]);
  const { data: blob, error, reload } = useRemoteResource(load);
  const qr = useObjectUrl(blob);

  const copy = async () => {
    try { await navigator.clipboard.writeText(event.link); notify('Event link copied.'); }
    catch { notify('Could not copy. Select the event link below the QR code.', true); }
  };
  const download = () => {
    if (!qr) return;
    const anchor = document.createElement('a');
    anchor.href = qr; anchor.download = `event-${event.id}.png`; anchor.click();
  };

  return <Section className="qr-page" header="Event QR code"
    footer="Students scan this QR code with their camera. Registration and questions happen in the bot.">
    <div className="share-content">
      <div className="qr-wrap">{qr ? <img id="event-qr" src={qr} alt="Scan to register for this event" width={300} height={300} />
        : error ? <Button type="button" mode="bezeled" onClick={reload}>Retry QR</Button>
          : <Spinner size="m" />}</div>
      {error ? <Caption className="danger" role="status">{error}</Caption> : null}
      <Caption className="muted">PNG · Transparent background</Caption>
      <Button type="button" stretched disabled={!qr} onClick={download}>Download PNG</Button>
      <a href={event.link} className="event-link" target="_blank" rel="noopener noreferrer">{event.link}</a>
      <Button type="button" stretched mode="bezeled" onClick={copy}>Copy event link</Button>
    </div>
  </Section>;
}
