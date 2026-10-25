export type QuestionType = 'text' | 'number' | 'single_choice' | 'multiple_choice';

export interface Question {
  id: string;
  label: string;
  type: QuestionType;
  required: boolean;
  options: string[];
}

export interface Event {
  id: string;
  title: string;
  description: string;
  registration_open: boolean;
  questions: Question[];
  response_retention_days: number;
  revision: number;
  form_revision: number;
  form_locked: boolean;
  created_at: string;
  department: string;
}

export interface EventDetails extends Event { link: string; qr_styling_enabled: boolean }
export interface QrDesign {
  id: string;
  status: 'generating' | 'verifying' | 'ready' | 'failed';
  error: string;
  elapsed_seconds: number;
  retry_after: number;
}
export interface QrDesignSelection { selected: QrDesign | null; active: QrDesign | null; retry_after: number }
export interface Pagination { page: number; pages: number; total: number }
export interface EventsPage extends Pagination { forms: (Event & { members: number })[] }

export type CellValue = string | string[] | boolean | null;
export interface TableColumn { id: string; label: string; type: 'text' | 'number' | 'choice' | 'checkbox' | 'date'; options: string[] }
export interface CellChange { revision: number; scope: 'answer' | 'column'; field: string; value: CellValue }
export interface Broadcast { id: string; event_id: string; status: string; revision: number; total: number; counts: Record<string, number>; content_kind: string | null; compose_url: string; message_url?: string | null; created_at: string; expires_at: string }
export interface BroadcastsPage extends Pagination { broadcasts: Broadcast[]; has_active: boolean }

export interface Member {
  telegram_id: number;
  student_id: string;
  name: string;
  telegram_username: string | null;
  email: string;
  phone_number: string | null;
  education_level: string | null;
  answers: Record<string, string | string[]> | null;
  answers_expires_at: string | null;
  organizer_values: Record<string, CellValue>;
  row_revision: number;
  editable_until: string;
}

export interface MembersPage extends Pagination { members: Member[]; questions: Question[]; columns: TableColumn[]; columns_revision: number }
export type Notify = (message: string, error?: boolean) => void;
