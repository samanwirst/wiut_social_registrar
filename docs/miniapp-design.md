# Mini App interface references

Reviewed on 2026-10-22. This review uses public product screenshots, a product announcement, the TelegramUI source, and Telegram's platform documentation. Financial accounts were not opened or connected.

| Reference | Observed interface pattern | Application to Event Studio |
| --- | --- | --- |
| [Wallet / Walt](https://walt.io/), including its [official product screenshot](https://walt.io/images/hero/hero_device_still.webp) | A clear focal point, a small set of primary actions, rounded groups of rows, and secondary details beneath primary labels. | Put the event list first. Keep names prominent, participant counts secondary, and status separate. |
| [Crypto Bot design update](https://t.me/CryptoBotEN/344) | Persistent bottom navigation separates Wallet, Trade, Swap, and More; the announcement describes one-tap access between sections. | Keep destinations predictable. Our existing per-event Overview, Questions, and Participants sections share one event context. A separate global tab bar is unnecessary for the current single event-list destination. |
| [Telegram's Mini App design guidelines](https://core.telegram.org/bots/webapps#design-guidelines) and [Durger King example](https://t.me/DurgerKingBot) | Mobile-first layouts, familiar interaction patterns, readable labels, dynamic Telegram colors, and safe-area support. | Fit narrow Telegram Desktop windows as well as phones, retain keyboard access and Telegram BackButton, and check actual host palettes. Durger King's public website was unavailable during this review; it was considered a documented platform example, not a live product inspection. |
| [TelegramUI](https://github.com/telegram-mini-apps-dev/TelegramUI) | Platform-aware building blocks rather than a complete application design. | Use its controls and typography, with application-specific grouping, density, and browser-style resets. |

## Decisions for this application

- Start the event list with a single title and a short description. Telegram already provides the application's outer header.
- Present events as accessible list rows with a title, participant count, optional real description, and a compact open/closed label. Omit repeated placeholder descriptions and zero-question metadata.
- Use Telegram theme colors for surfaces and actions. Blend secondary text toward the foreground to keep small text readable in custom themes; retain a readable fallback when CSS color mixing is unavailable.
- Reset the user-agent background, border, and appearance on `Cell` components rendered as buttons. Keep their native keyboard behavior and focus indication.
- Show pagination when multiple pages exist. Keep the participant page size at 10.
- Preserve chat-based student questionnaires and the separate organizer interface.
- Keep the per-event Overview, Questions, Participants, and QR sections together, with consistent back navigation and protection for unsaved changes. QR exports have their own page and a transparent PNG download.

## Regression checks

The browser integration script exercises a 386px-wide Telegram Desktop night palette in addition to generic light/dark and iOS layouts. It checks that event rows have no user-agent button chrome, secondary event text reaches a contrast ratio of at least 4.5:1, one-page pagination is absent, and the page fits horizontally. Existing checks cover questionnaires, failed-save recovery, participant pagination, safe areas, and back navigation.
