import { cloneElement, useId } from 'react';
import type { ReactElement } from 'react';
import { Caption } from '@telegram-apps/telegram-ui';

// Input's built-in header is hidden on iOS. Keep visible labels on every platform.
export function Field({ label, children }: { label: string; children: ReactElement<{ id?: string }> }) {
  const id = useId();
  return <div className="field"><label htmlFor={id}><Caption className="muted">{label}</Caption></label>
    {cloneElement(children, { id })}</div>;
}
