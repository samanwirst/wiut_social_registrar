import { useCallback, useEffect, useRef, useState } from 'react';
import { api, ApiError, errorMessage } from '../api';
import type { QrDesign, QrDesignSelection } from '../types';

function backgroundPreference(eventId: string) {
  try { return localStorage.getItem(`qr-background:${eventId}`) !== 'false'; }
  catch { return true; }
}

export function useQrDesign(eventId: string) {
  const [transparent, changeTransparent] = useState(() => backgroundPreference(eventId));
  const [prompt, setPrompt] = useState('');
  const [design, setDesign] = useState<QrDesign | null>(null);
  const [completed, setCompleted] = useState<QrDesign | null>(null);
  const [restoring, setRestoring] = useState(true);
  const [resetting, setResetting] = useState(false);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState('');
  const [syncError, setSyncError] = useState('');
  const [notice, setNotice] = useState('');
  const [waitMessage, setWaitMessage] = useState('');
  const [revision, setRevision] = useState(0);
  const [now, setNow] = useState(Date.now);
  const [startedAt, setStartedAt] = useState(Date.now);
  const [cooldownUntil, setCooldownUntil] = useState(0);
  const pending = useRef(false);
  const mounted = useRef(true);
  const activeId = useRef<string>();
  const lostJob = useRef(false);
  const prefix = `/api/events/${encodeURIComponent(eventId)}/qr/designs`;
  const id = design?.id;
  const busy = starting || design?.status === 'generating' || design?.status === 'verifying';

  useEffect(() => {
    mounted.current = true;
    // A submitted mutation can finish after navigation. The server owns selection
    // and can resume it even in a completely new Telegram WebView.
    return () => { mounted.current = false; };
  }, []);

  useEffect(() => {
    if (!busy && cooldownUntil <= Date.now()) return;
    const timer = window.setInterval(() => {
      const current = Date.now();
      setNow(current);
      if (!busy && current >= cooldownUntil) window.clearInterval(timer);
    }, 1000);
    return () => window.clearInterval(timer);
  }, [busy, cooldownUntil]);

  const receive = useCallback((current: QrDesign) => {
    const time = Date.now();
    activeId.current = current.id;
    setDesign(current);
    setSyncError('');
    setNow(time);
    setStartedAt(time - Math.max(0, current.elapsed_seconds || 0) * 1000);
    setCooldownUntil(time + Math.max(0, current.retry_after || 0) * 1000);
    if (current.status === 'ready') setCompleted(current);
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    setRestoring(true);
    const restore = async () => {
      try {
        const state = await api<QrDesignSelection>(prefix, { signal: controller.signal });
        if (controller.signal.aborted) return;
        setCompleted(state.selected);
        const current = state.active ?? state.selected;
        if (current) receive(current);
        else { activeId.current = undefined; setDesign(null); setSyncError(''); }
        const time = Date.now();
        setNow(time);
        setCooldownUntil(time + state.retry_after * 1000);
        if (lostJob.current && !state.selected && !state.active)
          setNotice('This preview has expired — generate a new design when you are ready');
        lostJob.current = false;
        setRestoring(false);
      } catch (failure) {
        if (!controller.signal.aborted) setSyncError(errorMessage(failure));
      }
    };
    void restore();
    return () => controller.abort();
  }, [prefix, receive, revision]);

  useEffect(() => {
    if (!id) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const current = await api<QrDesign>(`${prefix}/${encodeURIComponent(id)}`, { signal: controller.signal });
        if (controller.signal.aborted || activeId.current !== id) return;
        receive(current);
        if (current.status === 'generating' || current.status === 'verifying') timer = setTimeout(() => { void poll(); }, 2000);
      } catch (failure) {
        if (controller.signal.aborted || activeId.current !== id) return;
        if (failure instanceof ApiError && failure.status === 404) {
          activeId.current = undefined;
          setDesign(null);
          lostJob.current = true;
          setRestoring(true);
          setRevision(value => value + 1);
        } else setSyncError(errorMessage(failure));
      }
    };
    void poll();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [id, prefix, receive, revision]);

  const generate = useCallback(async (value: string) => {
    if (pending.current) return;
    pending.current = true;
    const time = Date.now();
    setStarting(true);
    setNow(time);
    setStartedAt(time);
    setError('');
    setSyncError('');
    setNotice('');
    setWaitMessage('');
    try {
      const current = await api<QrDesign>(prefix, { method: 'POST', body: JSON.stringify({ prompt: value }) });
      if (mounted.current) receive(current);
    } catch (failure) {
      if (!mounted.current) return;
      if (failure instanceof ApiError && failure.status === 429 && failure.retryAfter > 0) {
        const current = Date.now();
        setNow(current);
        setCooldownUntil(current + failure.retryAfter * 1000);
        setWaitMessage(failure.message);
      } else setError(errorMessage(failure));
    } finally {
      pending.current = false;
      if (mounted.current) setStarting(false);
    }
  }, [prefix, receive]);

  const reset = useCallback(async () => {
    if (pending.current) return;
    pending.current = true;
    setResetting(true);
    try {
      const state = await api<QrDesignSelection>(prefix, { method: 'DELETE' });
      if (!mounted.current) return;
      activeId.current = undefined;
      setDesign(null);
      setCompleted(null);
      setError('');
      setSyncError('');
      setNotice('');
      const time = Date.now();
      setNow(time);
      setCooldownUntil(time + state.retry_after * 1000);
    } catch (failure) {
      if (mounted.current) setSyncError(errorMessage(failure));
    } finally {
      pending.current = false;
      if (mounted.current) setResetting(false);
    }
  }, [prefix]);
  const setTransparent = useCallback((value: boolean) => {
    changeTransparent(value);
    try { localStorage.setItem(`qr-background:${eventId}`, String(value)); }
    catch { /* The preference is optional; artwork is always restored from the server. */ }
  }, [eventId]);
  const retry = useCallback(() => { setSyncError(''); setRevision(value => value + 1); }, []);
  const cooldown = Math.max(0, Math.ceil((cooldownUntil - now) / 1000));

  return { design, completed, generate, reset, starting, restoring, resetting, error, syncError, busy, cooldown,
    notice: notice || (cooldown > 0 ? waitMessage : ''),
    elapsed: Math.max(0, Math.floor((now - startedAt) / 1000)),
    transparent, setTransparent, prompt, setPrompt, retry };
}
