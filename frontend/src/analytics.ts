import { useEffect } from 'react';
import { telegram } from './telegram';

type Screen = 'forms' | 'overview' | 'questions' | 'participants' | 'qr' | 'answer' | 'columns' | 'messages';
type Event = { id: string; name: string; form_id?: string; duration_ms?: number; [key: string]: unknown };
const sessionId = crypto.randomUUID();
let queue: Event[] = [];
let sending = false;
let current: { screen: Screen; form_id?: string } = { screen: 'forms' };
let installed = false;
let timer = 0;

export function track(name: string, data: Record<string, unknown> = {}) {
  if (!telegram?.initData || location.pathname.startsWith('/admin')) return;
  if (queue.length < 100) queue.push({ id: crypto.randomUUID(), name, ...current, ...data });
}

async function flush() {
  if (sending || !queue.length) return;
  sending = true;
  const batch = queue.splice(0, 20);
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), 5000);
  try {
    await fetch('/api/analytics', { method: 'POST', signal: controller.signal, keepalive: true,
      credentials: 'omit', cache: 'no-store',
      headers: { Authorization: `tma ${telegram?.initData ?? ''}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: sessionId, events: batch }) });
    // Deliberately bounded best effort. Never recursively report telemetry failures.
  } catch { /* No message content, credentials, or telemetry are stored in the browser. */ }
  finally { window.clearTimeout(timeout); sending = false; }
}

const selectors: [string, string][] = [
  ['.event-card', 'open_form'], ['#save-event', 'save_form'], ['.export-xlsx', 'export_xlsx'],
  ['.selection-cell thead input', 'select_all'], ['thead .selection-cell input', 'select_all'],
  ['tbody .selection-cell input', 'select_person'], ['.cell-value', 'edit_answer'],
  ['.cell-action[type=submit]', 'save_answer'], ['.cell-dismiss', 'discard_answer'],
  ['.cell-expand', 'open_answer'], ['.media-answer a', 'open_media'],
];

export function useInterfaceAnalytics() {
  useEffect(() => {
    if (installed || !telegram?.initData) return;
    installed = true;
    track('panel_opened', { platform: telegram.platform, width: innerWidth, height: innerHeight });
    const click = (event: MouseEvent) => {
      const target = event.target instanceof Element ? event.target : null;
      const control = target?.closest<HTMLElement>('[data-analytics], button, a, input[type=checkbox], select');
      if (!control || control.matches(':disabled') || control.getAttribute('aria-disabled') === 'true') return;
      let action = control.dataset.analytics;
      if (!action) action = selectors.find(([selector]) => control.matches(selector))?.[1];
      track('ui_action', { action: action ?? 'other_control' });
    };
    const focus = (event: FocusEvent) => {
      if (event.target instanceof Element && event.target.matches('input:not([type=checkbox]), textarea, select')) {
        track('ui_action', { action: 'field_interaction' });
      }
    };
    const invalid = () => track('client_error', { error: 'validation' });
    const runtimeError = () => track('client_error', { error: 'internal' });
    const visibility = () => { if (document.visibilityState === 'hidden') void flush(); };
    document.addEventListener('click', click, true);
    document.addEventListener('focusin', focus);
    document.addEventListener('invalid', invalid, true);
    window.addEventListener('error', runtimeError);
    window.addEventListener('unhandledrejection', runtimeError);
    document.addEventListener('visibilitychange', visibility);
    window.addEventListener('pagehide', flush);
    timer = window.setInterval(() => { void flush(); }, 3000);
    return () => {
      installed = false;
      window.clearInterval(timer);
      document.removeEventListener('click', click, true);
      document.removeEventListener('focusin', focus);
      document.removeEventListener('invalid', invalid, true);
      window.removeEventListener('error', runtimeError);
      window.removeEventListener('unhandledrejection', runtimeError);
      document.removeEventListener('visibilitychange', visibility);
      window.removeEventListener('pagehide', flush);
      void flush();
    };
  }, []);
}

export function useAnalyticsScreen(screen: Screen, formId?: string) {
  useEffect(() => {
    const previous = current;
    current = { screen, form_id: formId };
    track('screen_view');
    let since = performance.now();
    let visible = document.visibilityState === 'visible';
    const engage = () => {
      const duration = Math.min(15000, Math.round(performance.now() - since));
      if (visible && duration > 0 && current.screen === screen) {
        track('screen_engagement', { screen, form_id: formId, duration_ms: duration });
      }
      since = performance.now();
      visible = document.visibilityState === 'visible';
    };
    const interval = window.setInterval(engage, 15000);
    document.addEventListener('visibilitychange', engage);
    return () => {
      engage(); window.clearInterval(interval);
      document.removeEventListener('visibilitychange', engage);
      current = previous;
    };
  }, [screen, formId]);
}
