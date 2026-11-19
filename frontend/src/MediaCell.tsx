import type { MediaAnswer } from './types';
import { openTelegramChat } from './telegram';

export const mediaTypes = new Set(['photo', 'document', 'voice', 'video', 'audio', 'animation', 'video_note', 'media']);
const labels: Record<string, string> = { photo: 'Photo', document: 'File', voice: 'Voice message', video: 'Video', audio: 'Audio', animation: 'GIF', video_note: 'Video message' };

export function MediaCell({ value }: { value: MediaAnswer | null }) {
  return <td className="editable-cell media-cell">{value ? <button type="button" className="cell-value" onClick={() => openTelegramChat(value.url, { close: false })}>
    <span className="cell-preview">{value.file_name || labels[value.kind] || 'Attachment'}</span>
    <span className="cell-read-more">Open in Telegram</span>
  </button> : '—'}</td>;
}
