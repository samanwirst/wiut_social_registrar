# Mini App rules

- Use the existing React 18, TypeScript, TelegramUI, and official Telegram Web App SDK.
  Keep the current native Telegram appearance and both iOS/base themes.
- Components render UI. Extract repeated stateful behavior into focused custom hooks;
  share behavior, not mutable state between separate component instances.
- Keep effect dependencies explicit. Abort outdated requests, release object URLs, and
  unregister browser/Telegram listeners on unmount. Never disable hook dependency checks
  to force an effect to run once.
- Update event drafts immutably and keep stable question IDs. Preserve duplicate-save
  protection, revision conflicts, unsaved-change guards, and native BackButton behavior.
- `api.ts` owns authenticated transport and timeouts. Never use `initDataUnsafe` for access,
  cache personal API responses, put credentials in the bundle, or enable Vite `.env` loading.
- Students answer questions in bot chat. Form creation stays `/new_form` (`/new_event` remains a compatibility alias); QR export stays
  on its dedicated tab. Participants show contacts and Level, with ten rows per page.
- Run `npm run build --prefix frontend` from the repository root and the browser checks
  in `docs/testing.md`. Generated `dist/` and `node_modules/` stay ignored.
