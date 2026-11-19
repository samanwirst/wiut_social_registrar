let csrf = '';
export function setCsrf(value: string) { csrf = value; }

export async function adminApi<T>(path: string, options: RequestInit = {}): Promise<T> {
  const controller = new AbortController();
  const abort = () => controller.abort();
  if (options.signal?.aborted) abort();
  options.signal?.addEventListener('abort', abort, { once: true });
  const timeout = window.setTimeout(abort, 20000);
  try {
    const response = await fetch(`/admin/api/${path}`, { ...options, credentials: 'same-origin', cache: 'no-store',
      signal: controller.signal, headers: { 'Content-Type': 'application/json', 'X-Analytics-Request': '1', 'X-CSRF-Token': csrf } });
    const data = await response.json();
    if (!response.ok) {
      if (response.status === 401 && !['login', 'verify'].includes(path)) window.dispatchEvent(new Event('analytics-session-expired'));
      throw new Error(data.error ?? 'Could not load analytics');
    }
    return data;
  } finally {
    window.clearTimeout(timeout);
    options.signal?.removeEventListener('abort', abort);
  }
}
