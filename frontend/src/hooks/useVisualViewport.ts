import { useEffect, useState } from 'react';

const viewport = () => ({ height: window.visualViewport?.height ?? window.innerHeight, top: window.visualViewport?.offsetTop ?? 0 });

/** Keep the reading/editor surface and its actions above the software keyboard. */
export function useVisualViewport() {
  const [size, setSize] = useState(viewport);
  useEffect(() => {
    const update = () => {
      const next = viewport();
      setSize(previous => previous.height === next.height && previous.top === next.top ? previous : next);
    };
    window.visualViewport?.addEventListener('resize', update);
    window.visualViewport?.addEventListener('scroll', update);
    window.addEventListener('resize', update);
    return () => {
      window.visualViewport?.removeEventListener('resize', update);
      window.visualViewport?.removeEventListener('scroll', update);
      window.removeEventListener('resize', update);
    };
  }, []);
  return size;
}
