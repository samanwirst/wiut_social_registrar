import { createRoot } from 'react-dom/client';
import '@telegram-apps/telegram-ui/dist/styles.css';
import './style.css';
import { App } from './App';

createRoot(document.getElementById('app')!).render(<App />);
