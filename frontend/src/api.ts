import { telegram } from './telegram';

class ApiError extends Error {}

async function request(path: string, options: RequestInit = {}, responseType: 'json' | 'blob' = 'json') {
  const controller = new AbortController();
  const abort = () => controller.abort();
  if (options.signal?.aborted) controller.abort();
  options.signal?.addEventListener('abort', abort, { once: true });
  const timer = window.setTimeout(abort, 20000);
  try {
    const response = await fetch(path, {
      ...options, signal: controller.signal, credentials: 'omit', cache: 'no-store',
      headers: { Authorization: `tma ${telegram?.initData ?? ''}`, 'Content-Type': 'application/json' },
    });
    if (!response.ok) {
      const data = await response.json().catch(() => null);
      throw new ApiError(typeof data?.error === 'string' ? data.error : 'Please try again later.');
    }
    // Read within the timeout too, so a stalled response body cannot leave the UI busy.
    return responseType === 'blob' ? await response.blob() : await response.json();
  } catch (error) {
    if (error instanceof ApiError) throw error;
    throw new ApiError(controller.signal.aborted ? 'The request was interrupted. Please try again.'
      : 'Could not connect to the event panel. Please try again.');
  } finally {
    window.clearTimeout(timer);
    options.signal?.removeEventListener('abort', abort);
  }
}

export function api<T>(path: string, options?: RequestInit): Promise<T> { return request(path, options); }
export function eventQr(id: string, signal: AbortSignal): Promise<Blob> {
  return request(`/api/events/${encodeURIComponent(id)}/qr`, { signal }, 'blob');
}

export const errorMessage = (error: unknown) => error instanceof Error ? error.message : 'Please try again.';
