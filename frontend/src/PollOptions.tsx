import { useEffect, useRef } from 'react';
import { Button, Caption, IconButton, Input } from '@telegram-apps/telegram-ui';

const MIN_OPTIONS = 2;
const MAX_OPTIONS = 20;

export function PollOptions({ options, locked, disabled, onChange }: {
  options: string[]; locked: boolean; disabled: boolean; onChange: (options: string[]) => void;
}) {
  const inputs = useRef<(HTMLInputElement | null)[]>([]);
  const focusNext = useRef<number | null>(null);

  useEffect(() => {
    if (focusNext.current !== null) {
      inputs.current[focusNext.current]?.focus();
      focusNext.current = null;
    }
  }, [options.length]);

  const add = () => {
    if (locked || disabled || options.length >= MAX_OPTIONS) return;
    focusNext.current = options.length;
    onChange([...options, '']);
  };
  const remove = (index: number) => {
    if (locked || disabled || options.length <= MIN_OPTIONS) return;
    focusNext.current = Math.min(index, options.length - 2);
    onChange(options.filter((_, position) => position !== index));
  };

  return <fieldset className="poll-options" disabled={locked || disabled}>
    <legend><Caption className="muted">Options</Caption></legend>
    <div className="poll-option-list">{options.map((option, index) => <div className="poll-option-row" key={index}>
      {!locked ? <IconButton type="button" mode="plain" size="s" className="poll-option-remove" aria-label={`Remove option ${index + 1}`}
        disabled={disabled || options.length <= MIN_OPTIONS} onClick={() => remove(index)}>
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <circle cx="12" cy="12" r="10" fill="currentColor" /><path d="M7 12h10" stroke="var(--tgui--section_bg_color)" strokeWidth="2" strokeLinecap="round" />
        </svg>
      </IconButton> : null}
      <Input ref={node => { inputs.current[index] = node; }} aria-label={`Option ${index + 1}`} placeholder={`Option ${index + 1}`}
        value={option} maxLength={100} required disabled={locked || disabled}
        onChange={e => onChange(options.map((value, position) => position === index ? e.target.value : value))}
        onKeyDown={e => {
          if (e.key !== 'Enter' || e.nativeEvent.isComposing) return;
          e.preventDefault();
          if (index < options.length - 1) inputs.current[index + 1]?.focus(); else add();
        }} />
    </div>)}</div>
    {!locked ? <Button type="button" mode="plain" size="s" className="poll-option-add" before={<span aria-hidden="true">＋</span>}
      disabled={disabled || options.length >= MAX_OPTIONS} onClick={add}>Add option</Button> : null}
    <Caption className="muted poll-option-count">{options.length} / {MAX_OPTIONS} options · At least {MIN_OPTIONS} required</Caption>
  </fieldset>;
}
