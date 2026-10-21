import { useEffect } from 'react';
import type { MutableRefObject } from 'react';
import { supports, telegram } from '../telegram';

export function useUnsavedChanges(dirty: boolean, saving: MutableRefObject<boolean>, guard: MutableRefObject<() => boolean>) {
  useEffect(() => {
    guard.current = () => !saving.current && (!dirty || window.confirm('Discard your unsaved event changes?'));
    if (supports('6.2')) {
      if (dirty) telegram?.enableClosingConfirmation(); else telegram?.disableClosingConfirmation();
    }
    const beforeUnload = (event: BeforeUnloadEvent) => {
      if (dirty || saving.current) { event.preventDefault(); event.returnValue = ''; }
    };
    window.addEventListener('beforeunload', beforeUnload);
    return () => {
      guard.current = () => true;
      window.removeEventListener('beforeunload', beforeUnload);
      if (supports('6.2')) telegram?.disableClosingConfirmation();
    };
  }, [dirty, saving, guard]);
}
