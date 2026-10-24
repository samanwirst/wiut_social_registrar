# Mini App interface references

Reviewed on 2026-10-24. This review uses public product screenshots, a product announcement, Telegram's platform documentation, the Android client source, and the installed TelegramUI 2.1.13 source. Financial accounts were not opened or connected.

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

## Geometry and native interaction

The geometry below is our application mapping of Telegram's design patterns. It is
centralized in `frontend/src/style.css`; individual screens do not choose their own radii.

| Role | Geometry and behavior | Basis |
| --- | --- | --- |
| Grouped surfaces | 12px corners on event lists, settings, questions, participants, QR and the save bar; captions sit outside each group | [TelegramUI Section source](https://github.com/telegram-mini-apps-dev/TelegramUI/blob/main/src/components/Blocks/Section/Section.module.css) |
| Android/Desktop controls | 8px corners on fields and actions, including compact buttons | [Telegram Android outlined input](https://github.com/DrKLO/Telegram/blob/master/TMessagesProj/src/main/java/org/telegram/ui/Components/OutlineTextContainerView.java), [TelegramUI Button source](https://github.com/telegram-mini-apps-dev/TelegramUI/blob/main/src/components/Blocks/Button/Button.module.css) |
| iOS controls | 12px action corners, plain input rows inside groups, and segmented tabs with an inset selected surface | [TelegramUI form source](https://github.com/telegram-mini-apps-dev/TelegramUI/blob/main/src/components/Form/FormInput/FormInput.module.css) and its iOS platform variants |
| Spacing and alignment | A 4px spacing scale, 16px shared content inset, one workspace width across tabs, 44px minimum button targets and 48px input targets | Application layout based on [Telegram's responsive design and accessibility guidance](https://core.telegram.org/bots/webapps#design-guidelines) |
| Navigation | Plain Previous/Next labels, SVG chevrons for back/disclosure/reordering, and the same stroke weight for all navigation icons | Telegram client navigation patterns; text arrow characters are omitted |
| Focus and feedback | Shared focus rings, native disabled states, keyboard-operable tabs, fixed bottom actions, and notifications above the action area | The same platform design guidelines and TelegramUI controls |

The iOS selected tab radius is derived from its container radius minus its inset.
Circular contact switches and remove-option glyphs retain their semantic shapes.
These intentional differences do not create separate visual styles for each screen.

Native theme colors drive surfaces, separators, text, controls and hover states. The
official Web App API also matches Telegram's header, app background and bottom bar to
`secondary_bg_color`, including after a theme change. Header/background methods require
API 6.1; the bottom-bar method requires 7.10. Feature checks preserve older clients.
See [the Web App API](https://core.telegram.org/bots/webapps#initializing-mini-apps).

Both safe-area insets contribute to bottom action and notification placement. Form
content reserves space for the action bar, so its last controls remain scrollable.
The existing native BackButton and unsaved-change confirmation remain in use.

## Regression checks

The browser integration script exercises a 386px-wide Telegram Desktop night palette in addition to generic light/dark and iOS layouts. It checks that event rows have no user-agent button chrome, secondary event text reaches a contrast ratio of at least 4.5:1, one-page pagination is absent, and the page fits horizontally. Existing checks cover questionnaires, failed-save recovery, participant pagination, safe areas, and back navigation.

Typography follows TelegramUI's platform font metrics. Group dividers use the same
inset as their labels, and links use native accent colors with a hover underline.

The visual matrix renders all five screens in both appearances and both platform
variants. It verifies grouped/field/action radii, touch target sizes, absence of text
arrows, native chrome colors, and horizontal containment at 320px, 390px and 900px.
Additional checks exercise keyboard tab selection, top and bottom safe areas, and
notification/action-bar separation. Twenty primary screen captures and four scrolled
action-area captures are saved for visual review; Android/Desktop dark captures use
Telegram's blue night palette. A separate API 6.1 fixture verifies that older clients
skip unsupported bottom-bar calls.
