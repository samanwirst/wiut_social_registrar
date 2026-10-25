import { useLayoutEffect, useState } from 'react';

/** Measure the clamped text, including after table or viewport resizing. */
export function useTextOverflow(text: string) {
  const [node, ref] = useState<HTMLSpanElement | null>(null);
  const [overflowing, setOverflowing] = useState(false);
  useLayoutEffect(() => {
    if (!node) return;
    const measure = () => setOverflowing(node.scrollHeight > node.clientHeight + 1);
    measure();
    if (typeof ResizeObserver === 'undefined') {
      window.addEventListener('resize', measure);
      return () => window.removeEventListener('resize', measure);
    }
    const observer = new ResizeObserver(measure);
    observer.observe(node);
    return () => observer.disconnect();
  }, [text, node]);
  return { ref, overflowing };
}
