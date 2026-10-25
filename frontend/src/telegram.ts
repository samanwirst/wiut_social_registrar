import { useEffect, useState } from 'react';

interface TelegramWebApp {
  initData: string;
  platform: string;
  colorScheme: 'light' | 'dark';
  ready(): void;
  expand(): void;
  isVersionAtLeast(version: string): boolean;
  setHeaderColor?(color: string): void;
  setBackgroundColor?(color: string): void;
  setBottomBarColor?(color: string): void;
  onEvent(event: string, callback: () => void): void;
  offEvent(event: string, callback: () => void): void;
  enableClosingConfirmation(): void;
  disableClosingConfirmation(): void;
  openTelegramLink?(url: string): void;
  close?(): void;
  BackButton: { show(): void; hide(): void; onClick(callback: () => void): void; offClick(callback: () => void): void };
  HapticFeedback: { notificationOccurred(type: 'success' | 'error'): void };
}

declare global {
  interface Window { Telegram?: { WebApp: TelegramWebApp } }
}

export const telegram = window.Telegram?.WebApp;
export const supports = (version: string) => telegram?.isVersionAtLeast?.(version) !== false;

export function openTelegramChat(url: string) {
  if (telegram?.openTelegramLink) { telegram.openTelegramLink(url); telegram.close?.(); }
  else window.open(url, '_blank', 'noopener,noreferrer');
}

export function useTelegramBack(visible: boolean, onBack: () => void) {
  useEffect(() => {
    if (!supports('6.1')) return;
    if (visible) telegram?.BackButton?.show(); else telegram?.BackButton?.hide();
    telegram?.BackButton?.onClick(onBack);
    return () => { telegram?.BackButton?.offClick?.(onBack); telegram?.BackButton?.hide(); };
  }, [visible, onBack]);
}

const preferred = window.matchMedia('(prefers-color-scheme: dark)');
const currentAppearance = () => telegram?.colorScheme ?? (preferred.matches ? 'dark' : 'light');

export function useTelegramTheme() {
  const [appearance, setAppearance] = useState<'light' | 'dark'>(currentAppearance);
  useEffect(() => {
    const update = () => setAppearance(currentAppearance());
    telegram?.onEvent('themeChanged', update);
    preferred.addEventListener('change', update);
    return () => {
      telegram?.offEvent?.('themeChanged', update);
      preferred.removeEventListener('change', update);
    };
  }, []);
  useEffect(() => {
    document.documentElement.style.colorScheme = appearance;
    if (supports('6.1')) {
      telegram?.setHeaderColor?.('secondary_bg_color');
      telegram?.setBackgroundColor?.('secondary_bg_color');
    }
    if (supports('7.10')) telegram?.setBottomBarColor?.('secondary_bg_color');
  }, [appearance]);
  return { appearance, platform: (['ios', 'macos'].includes(telegram?.platform ?? '') ? 'ios' : 'base') as 'ios' | 'base' };
}
