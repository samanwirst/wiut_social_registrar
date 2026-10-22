import { Button, Caption } from '@telegram-apps/telegram-ui';
import type { Pagination as Page } from './types';

export function Pagination({ page, pages, onPage, disabled = false }: Page & { onPage: (page: number) => void; disabled?: boolean }) {
  if (pages <= 1) return null;
  return <nav className="pagination" aria-label="Pagination">
    <Caption>Page {page + 1} of {pages}</Caption>
    <div className="actions">
      <Button type="button" size="s" mode="bezeled" disabled={disabled || page === 0} onClick={() => onPage(page - 1)}>← Previous</Button>
      <Button type="button" size="s" mode="bezeled" disabled={disabled || page + 1 >= pages} onClick={() => onPage(page + 1)}>Next →</Button>
    </div>
  </nav>;
}
