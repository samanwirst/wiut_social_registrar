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
export interface EventsPage extends Pagination { events: (Event & { members: number })[] }

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
}

export interface MembersPage extends Pagination { members: Member[]; questions: Question[] }
export type Notify = (message: string, error?: boolean) => void;
