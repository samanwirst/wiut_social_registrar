import { useCallback, useEffect, useState } from 'react';
import type { FormEvent, ReactNode } from 'react';
import { adminApi, setCsrf } from './api';
import { useRemoteResource } from '../hooks/useRemoteResource';
import './analytics.css';

type Distribution = { label: string; count: number }[];
type Metrics = Record<string, number>;
interface Summary {
  inventory: Metrics; metrics: Metrics; collection_started_at: string | null;
  daily: { date: string; events: number; users: number; errors: number }[];
  registration_funnel: { stage: string; users: number; dropoff?: number; conversion?: number }[];
  actions: Distribution; platforms: Distribution; features: Distribution; education: Distribution; languages: Distribution;
  issues: { event: string; category: string; outcome: string; count: number; last_seen: string }[];
  performance: { route: string; requests: number; average_ms: number; maximum_ms: number; slow: number; errors: number }[];
  screens: { screen: string; visits: number; active_ms: number }[];
  stalled_registration: { stage: string; users: number }[];
  email: { status: string; count: number }[]; deliveries: { status: string; count: number }[];
  retention: { day: number; eligible: number; returned: number; rate: number }[];
  collector: { queued: number; dropped: number; write_failures: number; last_saved_at: string | null; retention_days: number };
  runtime: { component: string; ok: boolean; checked_at: string }[];
}
interface Paged { page: number; pages: number; total: number }
interface Forms extends Paged { forms: { id: string; title: string; anonymous: boolean; open: boolean; questions: number; opens: number; submissions: number }[] }
interface FormReport { id: string; title: string; anonymous: boolean; open: boolean; counts: Metrics; submissions: number;
  questions: { id: string; index: number; label: string; type: string; reached: number; answered: number; not_answered: number; conversion: number; average_ms: number; active_drafts: number; rejections: number }[] }
interface Users extends Paged { users: { id: string; label: string; created_at: string; last_seen_at: string; stage: string }[] }
interface Timeline extends Paged { events: { id: string; name: string; source: string; actor: string; form_id: string | null; at: string; duration_ms: number | null; outcome: string; properties: Record<string, string | number | boolean> }[];
  registration_history: { name: string; at: string }[] }
type Range = { start: string; end: string };
const date = (value: Date) => value.toISOString().slice(0, 10);
const period = (days: number): Range => ({ start: date(new Date(Date.now() - (days - 1) * 86400000)), end: date(new Date()) });
const number = (value: number) => value.toLocaleString('en-US');
const words = (value: string) => value.replaceAll('_', ' ');
const moment = (value?: string | null) => value ? new Date(value).toLocaleString() : 'No data yet';
const query = (range: Range) => new URLSearchParams(range).toString();

function Panel({ title, subtitle, children }: { title: string; subtitle?: string; children: ReactNode }) {
  return <section className="a-panel"><div className="a-panel-heading"><h2>{title}</h2>{subtitle ? <p>{subtitle}</p> : null}</div>{children}</section>;
}
function Stats({ values }: { values: [string, number, string?][] }) {
  return <div className="a-stats">{values.map(([label, value, hint]) => <article key={label}><span>{label}</span><strong>{number(value)}</strong>{hint ? <small>{hint}</small> : null}</article>)}</div>;
}
function Bars({ items }: { items: Distribution }) {
  const maximum = Math.max(1, ...items.map(item => item.count));
  return items.length ? <div className="a-bars">{items.map(item => <div key={item.label}><div><span>{words(item.label)}</span><b>{number(item.count)}</b></div>
    <div className="a-track"><div style={{ width: `${item.count / maximum * 100}%` }} /></div></div>)}</div> : <Empty />;
}
function Empty() { return <p className="a-empty">No activity in this period</p>; }
function Table({ headers, children }: { headers: string[]; children: ReactNode }) {
  return <div className="a-table-scroll" tabIndex={0}><table><thead><tr>{headers.map(header => <th key={header}>{header}</th>)}</tr></thead><tbody>{children}</tbody></table></div>;
}
function Pages({ data, onChange, busy }: { data: Paged; onChange: (page: number) => void; busy?: boolean }) {
  return <div className="a-pagination"><span>{number(data.total)} records · Page {data.page + 1} of {data.pages}</span><div>
    <button disabled={busy || data.page === 0} onClick={() => onChange(data.page - 1)}>Previous</button>
    <button disabled={busy || data.page + 1 >= data.pages} onClick={() => onChange(data.page + 1)}>Next</button></div></div>;
}
function LoadState({ loading, error, reload }: { loading: boolean; error: string | null; reload: () => void }) {
  return <>{loading ? <p role="status" className="a-loading">Loading analytics…</p> : null}{error ? <div role="alert" className="a-error">{error}<button onClick={reload}>Try again</button></div> : null}</>;
}

function Login({ onSignedIn }: { onSignedIn: () => void }) {
  const [telegramId, setTelegramId] = useState('');
  const [password, setPassword] = useState('');
  const [challenge, setChallenge] = useState('');
  const [code, setCode] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const submit = async (event: FormEvent) => {
    event.preventDefault(); if (busy) return;
    setBusy(true); setError('');
    try {
      if (challenge) {
        await adminApi('verify', { method: 'POST', body: JSON.stringify({ challenge_id: challenge, code }) });
        setCode(''); onSignedIn();
      } else {
        const result = await adminApi<{ challenge_id: string }>('login', { method: 'POST', body: JSON.stringify({ telegram_id: telegramId, password }) });
        setPassword(''); setChallenge(result.challenge_id);
      }
    } catch (failure) { setError(failure instanceof Error ? failure.message : 'Could not sign in'); }
    finally { setBusy(false); }
  };
  return <main className="analytics a-login"><div className="a-login-card"><span className="a-eyebrow">SOCIAL REGISTRAR</span>
    <h1>Understand every step</h1><p className="a-lead">Product analytics for your campus community</p>
    <form onSubmit={submit} aria-label="Administrator sign-in"><h2>{challenge ? 'Check your Telegram' : 'Administrator sign-in'}</h2>
      {challenge ? <><p>A one-time code was sent to your private chat with this bot<br />It expires in 5 minutes</p>
        <label>Telegram code<input key="code" autoFocus autoComplete="one-time-code" inputMode="numeric" pattern="[0-9]{6}" maxLength={64} value={code}
          onChange={event => setCode(event.target.value.replace(/[\s\u200B-\u200F\u202A-\u202E\u2066-\u2069\uFEFF]/g, ''))} required /></label></>
        : <><label>Telegram ID<input autoComplete="username" inputMode="numeric" value={telegramId} onChange={event => setTelegramId(event.target.value)} required /></label>
          <label>Password<input type="password" autoComplete="current-password" maxLength={128} value={password} onChange={event => setPassword(event.target.value)} required /></label></>}
      {error ? <p role="alert" className="a-error">{error}</p> : null}
      <button className="a-primary" type="submit" disabled={busy}>{busy ? 'Please wait…' : challenge ? 'Open analytics' : 'Send Telegram code'}</button>
      {challenge ? <button type="button" disabled={busy} onClick={() => { setChallenge(''); setCode(''); setError(''); }}>Start again</button> : null}
    </form><small>Restricted to configured bot administrators</small></div></main>;
}

function Daily({ items }: { items: Summary['daily'] }) {
  const [metric, setMetric] = useState<'users' | 'events' | 'errors'>('users');
  const maximum = Math.max(1, ...items.map(item => item[metric]));
  return <Panel title="Activity over time" subtitle="Daily totals in UTC"><div className="a-segments">{(['users', 'events', 'errors'] as const).map(value => <button key={value} aria-pressed={metric === value} onClick={() => setMetric(value)}>{words(value)}</button>)}</div>
    {items.length ? <><div className="a-chart" role="img" aria-label={`Daily ${metric}`}><svg viewBox="0 0 800 180" preserveAspectRatio="none">
      {[0, 1, 2, 3].map(line => <line key={line} x1="0" x2="800" y1={line * 50 + 10} y2={line * 50 + 10} />)}
      {items.map((item, index) => <rect key={item.date} x={index * 800 / items.length + 2} y={170 - item[metric] / maximum * 155}
        width={Math.max(1, 800 / items.length - 4)} height={Math.max(1, item[metric] / maximum * 155)} rx="3"><title>{item.date}: {number(item[metric])} {metric}</title></rect>)}</svg></div>
      <div className="a-chart-labels"><span>{items[0].date}</span><span>Peak {number(maximum)}</span><span>{items.at(-1)?.date}</span></div></> : <Empty />}</Panel>;
}

function Overview({ data }: { data: Summary }) {
  const { metrics: m, inventory: i } = data;
  return <><Stats values={[["Active users", m.active_users, 'Observed actions in this period'], ['New students', m.new_users], ['Registrations completed', m.completed_registrations], ['Form submissions', m.submissions]]} />
    <Daily items={data.daily} /><div className="a-grid"><Panel title="Across the whole bot" subtitle="Current database totals"><Stats values={[
      ['Users', i.users], ['Registered students', i.registered], ['Organizers', i.organizers], ['Forms', i.forms], ['Open forms', i.open_forms], ['Anonymous forms', i.anonymous_forms], ['Submissions', i.submissions], ['Active questionnaires', i.active_questionnaires]]} /></Panel>
      <Panel title="Most used features"><Bars items={data.features.slice(0, 10)} /></Panel>
      <Panel title="Email delivery" subtitle="Accepted means Microsoft accepted submission, not inbox delivery"><Bars items={data.email.map(item => ({ label: item.status, count: item.count }))} /></Panel>
      <Panel title="Broadcast delivery" subtitle="Current delivery outcomes updated in the selected period"><Bars items={data.deliveries.map(item => ({ label: item.status, count: item.count }))} /></Panel></div>
    {data.runtime.length ? <Panel title="Current service health" subtitle="Latest background probes; these checks never send verification emails"><Table headers={['Component', 'State', 'Last checked']}>
      {data.runtime.map(item => <tr key={item.component}><td>{words(item.component)}</td><td><span className={`a-badge ${item.ok ? 'ok' : 'error'}`}>{item.ok ? 'Available' : 'Unavailable'}</span></td><td>{moment(item.checked_at)}</td></tr>)}</Table></Panel> : null}</>;
}

function Registration({ data }: { data: Summary }) {
  const first = Math.max(1, data.registration_funnel[0]?.users ?? 0);
  return <><Panel title="Registration funnel" subtitle="Cohort: users first seen in the selected period · Reached each stage before the end of the period">
    <div className="a-funnel">{data.registration_funnel.map((step, index) => <div key={step.stage}><div><strong>{index + 1}. {step.stage}</strong><b>{number(step.users)}</b></div>
      <div className="a-track"><div style={{ width: `${Math.min(100, step.users / first * 100)}%` }} /></div>
      {index ? <small>{step.conversion}% from the previous step · {number(step.dropoff ?? 0)} did not reach this step</small> : null}</div>)}</div>
  </Panel><div className="a-grid"><Panel title="Where registration paused" subtitle="Unfinished accounts with no bot interaction for at least one hour"><Bars items={data.stalled_registration.map(item => ({ label: item.stage, count: item.users }))} /></Panel>
    <Panel title="Return visits" subtitle="A return action on day 1, 7 or 30 after the user's first interaction"><Table headers={['Day', 'Eligible users', 'Returned', 'Rate']}>
      {data.retention.map(item => <tr key={item.day}><td>{item.day}</td><td>{number(item.eligible)}</td><td>{number(item.returned)}</td><td>{item.rate}%</td></tr>)}</Table>
      <p className="a-note">Only cohorts with a fully elapsed return day are eligible · Historical clicks before analytics started are unavailable</p></Panel>
    <Panel title="Education levels" subtitle="All current accounts"><Bars items={data.education} /></Panel><Panel title="Telegram languages" subtitle="All current accounts"><Bars items={data.languages} /></Panel></div></>;
}

function Experience({ data }: { data: Summary }) {
  return <><div className="a-grid"><Panel title="Popular actions"><Bars items={data.actions} /></Panel><Panel title="Telegram platforms"><Bars items={data.platforms} /></Panel></div>
    <Panel title="Time in each screen" subtitle="Visible engagement, sampled every 15 seconds; not wall-clock session duration"><Table headers={['Screen', 'Engagement samples', 'Active time']}>
      {data.screens.map(item => <tr key={item.screen}><td>{words(item.screen)}</td><td>{number(item.visits)}</td><td>{Math.round(item.active_ms / 60000)} min</td></tr>)}</Table></Panel>
    <Panel title="Requests and response time" subtitle="Server timing · Slow means at least 2 seconds"><Table headers={['Operation', 'Requests', 'Average', 'Maximum', 'Slow', 'Errors']}>
      {data.performance.map(item => <tr key={item.route}><td><code>{item.route}</code></td><td>{number(item.requests)}</td><td>{number(item.average_ms)} ms</td><td>{number(item.maximum_ms)} ms</td><td>{number(item.slow)}</td><td>{number(item.errors)}</td></tr>)}</Table></Panel>
    <Panel title="Problems and rejected actions" subtitle="Categories only; message text and exception details are excluded"><Table headers={['Event', 'Category', 'Outcome', 'Count', 'Last seen']}>
      {data.issues.map(item => <tr key={`${item.event}:${item.category}:${item.outcome}`}><td>{words(item.event)}</td><td>{words(item.category)}</td><td><span className={`a-badge ${item.outcome}`}>{item.outcome}</span></td><td>{number(item.count)}</td><td>{moment(item.last_seen)}</td></tr>)}</Table></Panel></>;
}

function FormDetails({ id, range, onBack }: { id: string; range: Range; onBack: () => void }) {
  const load = useCallback((signal: AbortSignal) => adminApi<FormReport>(`forms/${encodeURIComponent(id)}?${query(range)}`, { signal }), [id, range]);
  const resource = useRemoteResource(load);
  const data = resource.data;
  return <><button onClick={onBack}>All forms</button><LoadState {...resource} />{data ? <><Panel title={data.title} subtitle={data.anonymous ? 'Anonymous form · Individual identities and journeys are unavailable' : 'Form performance'}>
    <Stats values={[["Link opens", data.counts.form_opened ?? 0], ['Questionnaires started', data.counts.form_started ?? 0], ['Submissions', data.submissions], ['Switched to another form', data.counts.form_switched ?? 0]]} /></Panel>
    <Panel title="Question-by-question progress" subtitle="Unique questionnaire attempts in this period · Repeat visits do not count twice"><Table headers={['Question', 'Type', 'Reached', 'Answered', 'Not answered', 'Conversion', 'Average time', 'Active drafts', 'Rejected']}>
      {data.questions.map(item => <tr key={item.id}><td><b>{item.index + 1}. {item.label}</b></td><td>{words(item.type)}</td><td>{item.reached}</td><td>{item.answered}</td><td>{item.not_answered}</td><td>{item.conversion}%</td><td>{Math.round(item.average_ms / 1000)} s</td><td>{item.active_drafts}</td><td>{item.rejections}</td></tr>)}</Table>
      <p className="a-note">“Not answered” includes people still completing a question · Active drafts are the current state · Older question revisions can have different labels</p></Panel></> : null}</>;
}

function FormList({ range }: { range: Range }) {
  const [page, setPage] = useState(0);
  const [selected, setSelected] = useState('');
  const load = useCallback((signal: AbortSignal) => adminApi<Forms>(`forms?${query(range)}&page=${page}`, { signal }), [range, page]);
  const resource = useRemoteResource(load);
  if (selected) return <FormDetails id={selected} range={range} onBack={() => setSelected('')} />;
  return <Panel title="Forms" subtitle="Submission counts use the selected period; open/closed status is current"><LoadState {...resource} />{resource.data ? <>
    <Table headers={['Form', 'Status', 'Mode', 'Questions', 'Link opens', 'Submissions']}>{resource.data.forms.map(form => <tr key={form.id}>
      <td><button className="a-link" onClick={() => setSelected(form.id)}>{form.title}</button></td><td>{form.open ? 'Open' : 'Closed'}</td><td>{form.anonymous ? 'Anonymous' : 'Identified'}</td><td>{form.questions}</td><td>{form.opens}</td><td>{form.submissions}</td></tr>)}</Table>
    <Pages data={resource.data} busy={resource.loading} onChange={setPage} /></> : null}</Panel>;
}

function Events({ range, userId, label }: { range: Range; userId?: string; label?: string }) {
  const [page, setPage] = useState(0);
  const [outcome, setOutcome] = useState('');
  const [source, setSource] = useState('');
  const load = useCallback((signal: AbortSignal) => adminApi<Timeline>(`events?${query(range)}&page=${page}&outcome=${outcome}&source=${source}${userId ? `&user_id=${userId}` : ''}`, { signal }), [range, page, outcome, source, userId]);
  const resource = useRemoteResource(load);
  return <><Panel title={label ? `${label} · Journey` : 'Activity log'} subtitle="A bounded event trail without message, answer or file contents">
    <div className="a-filters"><label>Outcome<select aria-label="Outcome" value={outcome} onChange={event => { setOutcome(event.target.value); setPage(0); }}><option value="">All</option>{['ok', 'rejected', 'error'].map(value => <option key={value}>{value}</option>)}</select></label>
      <label>Source<select aria-label="Source" value={source} onChange={event => { setSource(event.target.value); setPage(0); }}><option value="">All</option>{['bot', 'server', 'miniapp'].map(value => <option key={value}>{value}</option>)}</select></label></div>
    <LoadState {...resource} />{resource.data ? <><Table headers={['Time', 'Event', 'User', 'Outcome', 'Duration', 'Context']}>
      {resource.data.events.map(event => <tr key={event.id}><td>{moment(event.at)}</td><td>{words(event.name)}<small className="a-block">{event.source}</small></td><td>{event.actor}</td><td><span className={`a-badge ${event.outcome}`}>{event.outcome}</span></td><td>{event.duration_ms === null ? '—' : `${number(event.duration_ms)} ms`}</td><td>
        {Object.entries(event.properties).map(([key, value]) => <span className="a-context" key={key}>{words(key)}: {String(value)}</span>)}</td></tr>)}</Table>
      <Pages data={resource.data} busy={resource.loading} onChange={setPage} /></> : null}</Panel>
    {resource.data?.registration_history.length ? <Panel title="Registration history" subtitle="Persisted milestones, including history before UX analytics started"><Table headers={['Time', 'Milestone']}>
      {resource.data.registration_history.map((item, index) => <tr key={index}><td>{moment(item.at)}</td><td>{words(item.name)}</td></tr>)}</Table></Panel> : null}</>;
}

function People({ range }: { range: Range }) {
  const [page, setPage] = useState(0);
  const [selected, setSelected] = useState<{ id: string; label: string } | null>(null);
  const load = useCallback((signal: AbortSignal) => adminApi<Users>(`users?${query(range)}&page=${page}`, { signal }), [range, page]);
  const resource = useRemoteResource(load);
  if (selected) return <><button onClick={() => setSelected(null)}>All users</button><Events range={range} userId={selected.id} label={selected.label} /></>;
  return <Panel title="User journeys" subtitle="Pseudonymous users active in the selected period · Anonymous questionnaire actions are excluded from individual journeys"><LoadState {...resource} />{resource.data ? <>
    <Table headers={['User', 'Registration stage', 'First seen', 'Last bot interaction']}>{resource.data.users.map(user => <tr key={user.id}><td><button className="a-link" onClick={() => setSelected(user)}>{user.label}</button></td><td>{words(user.stage)}</td><td>{moment(user.created_at)}</td><td>{moment(user.last_seen_at)}</td></tr>)}</Table>
    <Pages data={resource.data} busy={resource.loading} onChange={setPage} /></> : null}</Panel>;
}

function Dashboard({ onLogout }: { onLogout: () => void }) {
  const [range, setRange] = useState<Range>(() => period(30));
  const [tab, setTab] = useState('Overview');
  const load = useCallback((signal: AbortSignal) => adminApi<Summary>(`summary?${query(range)}`, { signal }), [range]);
  const resource = useRemoteResource(load);
  const data = resource.data;
  return <div className="analytics"><header className="a-header"><div><span className="a-eyebrow">SOCIAL REGISTRAR</span><h1>Analytics</h1></div><div><button onClick={resource.reload} disabled={resource.loading}>Refresh</button><button onClick={onLogout}>Sign out</button></div></header>
    <main className="a-main"><div className="a-toolbar"><div><h2>Your community, in focus</h2><p>Registration, forms and organizer experience</p></div><div className="a-dates">
      <label>Period<select aria-label="Preset period" defaultValue="30" onChange={event => setRange(period(Number(event.target.value)))}>{[[1, 'Today'], [7, 'Last 7 days'], [30, 'Last 30 days'], [90, 'Last 90 days']].map(([value, title]) => <option value={value} key={value}>{title}</option>)}</select></label>
      <label>From (UTC)<input type="date" value={range.start} max={range.end} onChange={event => { if (event.target.value) setRange({ ...range, start: event.target.value }); }} /></label>
      <label>To (UTC)<input type="date" value={range.end} min={range.start} max={date(new Date())} onChange={event => { if (event.target.value) setRange({ ...range, end: event.target.value }); }} /></label></div></div>
      <nav className="a-tabs" aria-label="Analytics sections">{['Overview', 'Registration', 'Forms', 'Experience', 'Users', 'Activity'].map(value => <button key={value} aria-current={tab === value ? 'page' : undefined} onClick={() => setTab(value)}>{value}</button>)}</nav>
      <LoadState {...resource} />{data ? <><div className="a-coverage">UX collection started {moment(data.collection_started_at)} · Usage events retained for {data.collector.retention_days} days
        {data.collector.dropped || data.collector.write_failures ? <strong className="a-warning"> · Collection gaps: {data.collector.dropped} dropped events, {data.collector.write_failures} failed batches</strong> : null}</div>
        {tab === 'Overview' ? <Overview data={data} /> : tab === 'Registration' ? <Registration data={data} /> : tab === 'Forms' ? <FormList range={range} /> : tab === 'Experience' ? <Experience data={data} /> : tab === 'Users' ? <People range={range} /> : <Events range={range} />}</> : null}
      <footer className="a-footer">First-party analytics · No message contents, answers, verification codes or media files<br />Latest successful usage write: {moment(data?.collector.last_saved_at)}</footer>
    </main></div>;
}

export function AnalyticsApp() {
  const [authenticated, setAuthenticated] = useState<boolean | null>(null);
  const [failure, setFailure] = useState('');
  const restore = useCallback(async () => {
    setFailure('');
    try { const result = await adminApi<{ csrf: string }>('session'); setCsrf(result.csrf); setAuthenticated(true); }
    catch { setAuthenticated(false); }
  }, []);
  useEffect(() => {
    document.title = 'Social Registrar · Analytics';
    const expired = () => { setCsrf(''); setAuthenticated(false); };
    window.addEventListener('analytics-session-expired', expired);
    void restore();
    return () => window.removeEventListener('analytics-session-expired', expired);
  }, [restore]);
  const logout = async () => {
    try { await adminApi('logout', { method: 'POST', body: '{}' }); setCsrf(''); setAuthenticated(false); }
    catch (error) { setFailure(error instanceof Error ? error.message : 'Could not sign out'); }
  };
  return <>{failure ? <div className="analytics a-error" role="alert">{failure}</div> : null}{authenticated === null
    ? <main className="analytics a-login" role="status">Opening analytics…</main>
    : authenticated ? <Dashboard onLogout={() => { void logout(); }} /> : <Login onSignedIn={() => { void restore(); }} />}</>;
}
