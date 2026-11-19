import { createRoot } from 'react-dom/client';
import '@telegram-apps/telegram-ui/dist/styles.css';
import './style.css';
import { App } from './App';
import { AnalyticsApp } from './admin/AnalyticsApp';

createRoot(document.getElementById('app')!).render(location.pathname === '/admin' || location.pathname.startsWith('/admin/') ? <AnalyticsApp /> : <App />);
