import { useCallback, useEffect, useState } from 'react';
import { errorMessage } from '../api';

/** Each consumer owns its request; obsolete responses cannot replace current data. */
export function useRemoteResource<T>(load: (signal: AbortSignal) => Promise<T>) {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [revision, setRevision] = useState(0);
  const reload = useCallback(() => setRevision(value => value + 1), []);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError('');
    load(controller.signal)
      .then(result => { if (!controller.signal.aborted) setData(result); })
      .catch(error => { if (!controller.signal.aborted) setError(errorMessage(error)); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [load, revision]);

  return { data, loading, error, reload };
}

export function useObjectUrl(blob: Blob | null) {
  const [current, setCurrent] = useState<{ blob: Blob; url: string } | null>(null);
  useEffect(() => {
    if (!blob) { setCurrent(null); return; }
    const next = URL.createObjectURL(blob);
    setCurrent({ blob, url: next });
    return () => URL.revokeObjectURL(next);
  }, [blob]);
  return current?.blob === blob ? current.url : '';
}
