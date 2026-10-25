import { Button, Cell, Input, List, Section, Select, Switch } from '@telegram-apps/telegram-ui';
import type { Question, QuestionType } from './types';
import { Field } from './Field';
import { PollOptions } from './PollOptions';
import { Chevron, PlusIcon } from './Icons';

const types: [QuestionType, string][] = [
  ['text', 'Text response'], ['multiple_choice', 'Multiple choice'],
];

export function Questions({ questions, locked, disabled, onChange }: {
  questions: Question[]; locked: boolean; disabled: boolean; onChange: (questions: Question[]) => void;
}) {
  const change = (id: string, value: Partial<Question>) => onChange(questions.map(q => q.id === id ? { ...q, ...value } : q));
  const move = (index: number, offset: number) => {
    const next = [...questions];
    [next[index], next[index + offset]] = [next[index + offset], next[index]];
    onChange(next);
  };
  return <>
    <p className="notice">{locked
      ? 'Questions are locked after the first submission. Form details remain editable.'
      : 'Students answer these questions in the bot chat. Without questions, QR scans register verified students immediately.'}</p>
    <List className="section-list editor-fields">
      {questions.map((question, index) => <Section className="studio-section" key={question.id} header={`Question ${index + 1}${locked ? ' · Locked' : ''}`}>
        <div className="field-stack">
          <Field label="Question"><Input aria-label="Question" value={question.label} maxLength={200} required
            disabled={locked || disabled} placeholder="What would you like to ask?" onChange={e => change(question.id, { label: e.target.value })} /></Field>
          <Field label="Answer type">{question.type === 'number' || question.type === 'single_choice'
            ? <Input aria-label="Answer type" value={question.type === 'number' ? 'Number' : 'Single choice'} readOnly disabled />
            : <Select aria-label="Answer type" value={question.type} disabled={locked || disabled}
              onChange={e => {
                const type = e.target.value as QuestionType;
                change(question.id, { type, options: type === 'multiple_choice' && question.options.length < 2
                  ? [...question.options, ...Array(2 - question.options.length).fill('')] : question.options });
              }}>
              {types.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </Select>}</Field>
          {['single_choice', 'multiple_choice'].includes(question.type) ? <PollOptions options={question.options}
            locked={locked} disabled={disabled} onChange={options => change(question.id, { options })} /> : null}
        </div>
        <Cell Component="label" after={<Switch aria-label="Required question" checked={question.required} disabled={locked || disabled}
          onChange={e => change(question.id, { required: e.target.checked })} />}>Required question</Cell>
        {!locked ? <div className="question-actions actions">
          <Button type="button" size="s" mode="plain" aria-label={`Move question ${index + 1} up`} disabled={disabled || index === 0} onClick={() => move(index, -1)}><Chevron direction="up" /></Button>
          <Button type="button" size="s" mode="plain" aria-label={`Move question ${index + 1} down`} disabled={disabled || index === questions.length - 1} onClick={() => move(index, 1)}><Chevron direction="down" /></Button>
          <Button type="button" size="s" mode="plain" className="danger" disabled={disabled}
            onClick={() => onChange(questions.filter(q => q.id !== question.id))}>Remove</Button>
        </div> : null}
      </Section>)}
    </List>
    {!locked ? <Button type="button" mode="bezeled" stretched before={<PlusIcon />} disabled={disabled || questions.length >= 20}
      onClick={() => onChange([...questions, { id: crypto.randomUUID(), label: '', type: 'text', required: true, options: [] }])}>Add question</Button> : null}
  </>;
}
