export function Chevron({ direction = 'right' }: { direction?: 'left' | 'right' | 'up' | 'down' }) {
  return <svg className={`studio-icon chevron-${direction}`} width="20" height="20" viewBox="0 0 24 24"
    fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">
    <path d="m9 5 7 7-7 7" />
  </svg>;
}

export function PlusIcon() {
  return <svg className="studio-icon" width="20" height="20" viewBox="0 0 24 24" fill="none"
    stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true" focusable="false">
    <path d="M12 5v14M5 12h14" />
  </svg>;
}
