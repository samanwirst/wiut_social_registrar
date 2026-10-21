import { useEffect, useState } from 'react';

interface TelegramWebApp {
  initData: string;
  platform: string;
  colorScheme: 'light' | 'dark';
  ready(): void;
  expand(): void;
  isVersionAtLeast(version: string): boolean;
  onEvent(event: string, callback: () => void): void;
  offEvent(event: string, callback: () => void): void;
  enableClosingConfirmation(): void;
  disableClosingConfirmation(): void;
  BackButton: { show(): void; hide(): void; onClick(callback: () => void): void; offClick(callback: () => void): void };
  HapticFeedback: { notificationOccurred(type: 'success' | 'error'): void };
}

declare global {
  interface Window { Telegram?: { WebApp: TelegramWebApp } }
}

export const telegram = window.Telegram?.WebApp;
export const supports = (version: string) => telegram?.isVersionAtLeast?.(version) !== false;

export function useTelegramTheme() {
  const preferred = window.matchMedia('(prefers-color-scheme: dark)');
  const current = () => telegram?.colorScheme ?? (preferred.matches ? 'dark' : 'light');
  const [appearance, setAppearance] = useState<'light' | 'dark'>(current);
  useEffect(() => {
    const update = () => setAppearance(current());
    telegram?.onEvent('themeChanged', update);
    preferred.addEventListener('change', update);
    return () => {
      telegram?.offEvent?.('themeChanged', update);
      preferred.removeEventListener('change', update);
    };
  }, []);
  useEffect(() => { document.documentElement.style.colorScheme = appearance; }, [appearance]);
  return { appearance, platform: (['ios', 'macos'].includes(telegram?.platform ?? '') ? 'ios' : 'base') as 'ios' | 'base' };
}
