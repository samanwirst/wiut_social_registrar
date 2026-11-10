import { useEffect, useRef, useState } from 'react';
import { ApiError, api, errorMessage } from '../api';
import { showFileChat } from '../telegram';

interface Delivery { id: string; status: 'preparing' | 'sending' | 'sent' | 'failed' | 'unknown'; error: string; chat_url?: string }
export interface ChatFileOptions { kind: 'participants' | 'qr'; transparent: boolean; design_id: string; member_ids?: number[] }

export function useChatFile(eventId: string) {
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');
  const controller = useRef<AbortController | null>(null);
  const request = useRef<{ id: string; options: ChatFileOptions; accepted: boolean } | null>(null);
  useEffect(() => () => controller.current?.abort(), []);
  const send = async (options: ChatFileOptions) => {
    if (controller.current) return;
    if (!request.current || JSON.stringify(request.current.options) !== JSON.stringify(options)) {
      request.current = { id: crypto.randomUUID(), options, accepted: false };
    }
    const current = request.current;
    const path = `/api/forms/${encodeURIComponent(eventId)}/files`;
    const next = new AbortController();
    controller.current = next;
    setBusy(true); setError(''); setNotice('Sending to your chat');
    try {
      let result = current.accepted
        ? await api<Delivery>(`${path}/${current.id}`, { signal: next.signal })
        : await api<Delivery>(path, { method: 'POST', body: JSON.stringify({ request_id: current.id, ...current.options }), signal: next.signal });
      if (next.signal.aborted) return;
      current.accepted = true;
      if (result.chat_url) showFileChat(result.chat_url);
      const deadline = performance.now() + 150000;
      while (result.status === 'preparing' || result.status === 'sending') {
        if (performance.now() > deadline) throw new Error('This file is taking longer than expected');
        await new Promise<void>(resolve => {
          const finish = () => { window.clearTimeout(timer); next.signal.removeEventListener('abort', finish); resolve(); };
          const timer = window.setTimeout(finish, 1500);
          next.signal.addEventListener('abort', finish, { once: true });
        });
        if (next.signal.aborted) return;
        result = await api<Delivery>(`${path}/${current.id}`, { signal: next.signal });
      }
      if (result.status === 'sent') { setNotice('Sent to your chat'); request.current = null; }
      else {
        setNotice(''); setError(result.error);
        // An unconfirmed Telegram submission must never be automatically sent again.
        if (result.status === 'failed') request.current = null;
      }
    } catch (failure) {
      if (!next.signal.aborted) {
        if (!current.accepted && failure instanceof ApiError && [400, 401, 403, 429].includes(failure.status)) request.current = null;
        setNotice(''); setError(`${errorMessage(failure)} Check your chat before sending again`);
      }
    } finally {
      if (!next.signal.aborted) { controller.current = null; setBusy(false); }
    }
  };
  return { send, busy, notice, error };
}
