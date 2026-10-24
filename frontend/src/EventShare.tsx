import { useCallback, useRef } from 'react';
import { Button, Caption, Cell, Section, Spinner, Switch, Textarea } from '@telegram-apps/telegram-ui';
import { eventQr } from './api';
import { Field } from './Field';
import { CheckIcon } from './Icons';
import type { useQrDesign } from './hooks/useQrDesign';
import { useObjectUrl, useRemoteResource } from './hooks/useRemoteResource';
import type { EventDetails, Notify } from './types';

export function EventShare({ event, designer, notify }: {
  event: EventDetails; designer: ReturnType<typeof useQrDesign>; notify: Notify;
}) {
  const { transparent, setTransparent, prompt, setPrompt } = designer;
  const result = useRef<HTMLDivElement>(null);
  const designId = designer.completed?.id ?? '';
  const load = useCallback(async (signal: AbortSignal) => ({
    blob: designer.restoring ? null : await eventQr(event.id, signal, transparent, designId), transparent, designId,
  }), [event.id, transparent, designId, designer.restoring]);
  const { data, error, loading, reload } = useRemoteResource(load);
  const blob = !loading && data?.transparent === transparent && data?.designId === designId ? data.blob : null;
  const qr = useObjectUrl(blob);
  const failed = designer.error || (designer.design?.status === 'failed' ? designer.design.error : '');
  const phase = designer.starting ? 'Sending your request'
    : designer.design?.status === 'verifying' ? 'Checking QR readability' : 'Creating your image';
  const elapsed = `${Math.floor(designer.elapsed / 60)}:${String(designer.elapsed % 60).padStart(2, '0')}`;

  const copy = async () => {
    try { await navigator.clipboard.writeText(event.link); notify('Event link copied.'); }
    catch { notify('Could not copy. Select the event link below the QR code.', true); }
  };
  const download = () => {
    if (!qr) return;
    const anchor = document.createElement('a');
    anchor.href = qr; anchor.download = `event-${event.id}${designId ? '-design' : ''}.png`; anchor.click();
  };
  const generate = () => {
    if (designer.busy || designer.restoring || designer.resetting || designer.cooldown > 0 || !prompt.trim()) return;
    void designer.generate(prompt);
    result.current?.scrollIntoView({
      behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth', block: 'start',
    });
  };

  return <Section className="studio-section qr-page" header="Event QR code"
    footer="Students scan this QR code with their camera. Registration and questions happen in the bot.">
    <div className="share-content">
      <form className="qr-designer" aria-label="QR design" onSubmit={e => { e.preventDefault(); generate(); }}>
        <Field label="Describe your design"><Textarea aria-label="Design prompt" rows={3} maxLength={1200} value={prompt}
          disabled={!event.qr_styling_enabled} placeholder="Describe the theme, colors, and style you have in mind"
          onChange={e => setPrompt(e.target.value)} /></Field>
        <Cell className="qr-background" Component="label" multiline
          subtitle={transparent ? 'For light backgrounds and print layouts' : 'Include artwork around your QR code'}
          after={<Switch aria-label="Transparent background" checked={transparent}
            onChange={e => setTransparent(e.target.checked)} />}>Transparent background</Cell>
        <Button type="submit" stretched
          disabled={!event.qr_styling_enabled || !prompt.trim() || designer.busy || designer.restoring || designer.resetting || designer.cooldown > 0}>
          {designer.busy ? 'Creating design' : designer.cooldown > 0 ? `Generate again in ${designer.cooldown}s` : 'Generate design'}</Button>
        {!event.qr_styling_enabled ? <Caption className="muted">AI designs are not enabled yet — standard QR downloads are available</Caption> : null}
        {designer.notice ? <Caption className="muted" role="status">{designer.notice}</Caption> : null}
      </form>
      <div className="qr-result" ref={result}>
        <div className="qr-result-heading"><strong role="status" aria-live="polite">{designer.restoring
          ? designer.syncError ? 'Connection interrupted' : 'Restoring your design'
          : designer.resetting ? 'Switching to standard QR' : designer.busy
          ? designer.syncError ? 'Connection interrupted' : phase
          : designId ? failed ? 'Previous design' : 'Your design' : 'Event QR'}</strong>
          {designer.busy ? <Caption className="muted" aria-label="Elapsed time">{elapsed}</Caption>
            : qr && designId ? <span className="qr-ready"><CheckIcon />Ready</span> : null}</div>
        {designer.restoring || designer.resetting ? <div className="qr-preview-loading" role="status">
          <Spinner size="m" /><Caption>{designer.syncError ? 'Reconnect to load your saved QR code' : 'Loading your QR code'}</Caption>
        </div> : designer.busy ? <div className="qr-progress">
          <div className="qr-generation-canvas" aria-hidden="true"><Spinner size="l" /></div>
          <div className="qr-progress-copy">
            <Caption className="muted">{designer.syncError ? 'Your design may still be generating — reconnect to check'
              : 'You can leave this tab — your design will keep generating'}</Caption>
          </div>
          <ol className="qr-generation-stages" aria-label="Generation steps">
            <li aria-current={designer.design?.status !== 'verifying' ? 'step' : undefined} className={designer.design?.status === 'verifying' ? 'complete' : 'current'}>Create artwork</li>
            <li aria-current={designer.design?.status === 'verifying' ? 'step' : undefined} className={designer.design?.status === 'verifying' ? 'current' : ''}>Check QR</li>
          </ol>
        </div> : <>
          <div className="qr-wrap">{qr ? <img id="event-qr" src={qr} alt="Scan to register for this event" width={300} height={300} />
            : error ? <Button type="button" mode="bezeled" onClick={reload}>Retry preview</Button>
              : <div className="qr-preview-loading" role="status"><Spinner size="m" /><Caption>Preparing your PNG</Caption></div>}</div>
          {error ? <Caption className="danger" role="alert">{error}</Caption> : null}
          <Caption className="muted">PNG · {transparent ? 'Transparent' : 'Opaque'} background{designId ? ' · Scan checked' : ''}</Caption>
          <Button type="button" stretched disabled={!qr} onClick={download}>Download PNG</Button>
          {qr && transparent ? <Caption className="muted qr-surface-hint">Place on a light surface so the QR stays easy to scan</Caption> : null}
        </>}
        {!designer.busy && failed ? <div className="qr-design-error" role="alert"><strong>Couldn't create this design</strong>
          <Caption>{failed}</Caption>{designId ? <Caption className="muted">Your previous design is still available above</Caption> : null}</div> : null}
        {designer.syncError ? <Button type="button" stretched mode="bezeled" onClick={designer.retry}>Reconnect</Button> : null}
        {designer.design && !designer.restoring && !designer.resetting && (!designer.busy || designer.syncError)
          ? <Button type="button" mode="plain" onClick={() => { void designer.reset(); }}>Use standard QR</Button> : null}
      </div>
      <a href={event.link} className="event-link" target="_blank" rel="noopener noreferrer">{event.link}</a>
      <Button type="button" stretched mode="bezeled" onClick={copy}>Copy event link</Button>
    </div>
  </Section>;
}
