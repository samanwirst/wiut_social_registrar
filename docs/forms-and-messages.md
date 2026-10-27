# Forms, editable tables, and messages

Create a form with `/new_form Form name`, then open **Manage form** or `/panel`.
Set its name, description, and optional department, such as a club or the Students' Union.
Every form shares identity verification, chat questions, QR invitations, and organizer-only
tables. There is no form-type selection: the same workflow supports events, recruitment,
and other applications. `/new_event` remains an alias, and `event_<uuid>` invitations remain
supported without copying profiles or registrations.

For an advisor call, set its name and department, add application questions, and share
its QR/link. Students verify their identity once and answer each form in chat. The
organizer can track decisions using columns such as Status, Score, or Interview date.

## Edit the table

The **People** tab shows ten rows per page. Text cells preview up to three lines; **Read more**
opens the full answer with its question and student identity. The reading surface fills the
available phone viewport and becomes a side panel in wide windows. Paragraphs and literal
text are preserved and selectable, without opening the keyboard. **Edit** opens a spacious
text field; **Save** returns to the full saved answer. The native Telegram Back button or
close button returns to the same table page, scroll position, and selected audience.
Unsaved answer changes require confirmation before closing; pending saves cannot be dismissed.
Errors keep the typed draft in the editor. The surface follows viewport/keyboard resizing.

Short responses and organizer values can be edited in the table. The editor follows the
type: text, number, choice, checkbox, or date. Text editors also offer **Expand editor** to
move a typed draft into the full editor. The existing 2,000-character text limit remains.
The checkmark saves the cell; the cross closes it without a write. The compact controls
sit beside the field. Required questions and valid choice options remain enforced.
Verified IDs, names, contacts, and education levels
are read-only: organizers cannot overwrite a student's profile or verification.
Choice response edits accept one option, matching the bot questionnaire. Older multi-option
answers stay intact until the organizer explicitly replaces them with one choice.

**Columns** manages up to 20 organizer-only columns, even after applicant questions are
locked. Stable IDs preserve values when labels change. Labels and choice options can
be edited; changing the type requires a new column. Removing a column also removes its
values after confirmation. Submitted question definitions remain locked.

Row and column revisions detect concurrent edits. A conflict leaves the typed value in
the editor and asks for a refresh instead of silently overwriting another edit. Responses
are not stored in browser storage. Answers and organizer cells are temporary: their
deadline follows the form's retention period (30 days by default). Editing never extends
it. Shortening retention applies to existing rows; extending it cannot reopen an expired
editing window. Expired values disappear immediately and are physically cleaned up.
Attendance and the verified student profile remain permanent.

The green **Export .xlsx** button downloads the entire People table, independent of pagination
and audience selection. A single Participants worksheet contains contacts, education level,
current question responses, and organizer columns, with a standard Excel table, filters,
wrapped text, and frozen headers/identity columns. IDs and phone numbers stay literal text;
numeric/date/checkbox columns keep their supported types. All user text is written as text,
including strings beginning with `=`, so downloaded responses cannot become formulas.
Duplicate header labels receive unique suffixes. Expired answers and organizer values are
blank while attendance/contacts remain. Empty forms still produce a workbook with headers.

Both `/api/forms/{id}/members.xlsx` and the legacy `/api/events/{id}/members.xlsx` require
signed Telegram authentication and organizer ownership. Exports use the same expiry-filtered
member projection as the panel, return `Cache-Control: no-store`, and are never saved on the
server. Workbook generation runs in a background thread; one export at a time per process
prevents overlapping workbook construction. A cancelled request retains that slot until its
writer exits. The Mini App downloads the authenticated response as a blob and releases its
object URL when replaced or closed. This uses standard `.xlsx` without macros or external links.

## Message selected people

1. Select individual row checkboxes or the current page. The count includes selections
   across pages. Clear selection resets it.
2. Choose **Prepare message**. This saves an idempotent audience draft and immediately
   opens the bot chat to compose the message; recipients receive nothing yet.
3. Reply to **Write your message** using Telegram's own formatting: bold, italic, links,
   spoilers, rich messages, or one photo/document with a caption. Albums and unrelated
   messages are not treated as broadcast content.
4. Review the exact preview and audience count. The bot appends an italic *By Form name*
   attribution after the message (or its caption), using the form's name when the preview
   is prepared. Leave room for this footer within Telegram's text/caption limits.
   Choose **Send to …** or **Edit message**.
   Only the owner can confirm; older buttons cannot submit a replacement.
   The bot's saved preview is the source, so editing the original or renaming the form
   cannot change a confirmed message.
5. The **Messages** section at the bottom of **People** shows only **Finished** broadcasts,
   with delivery counts. Drafts and in-progress messages are hidden. Completed messages
   appear automatically while a queue is active, or after **Refresh**.
6. Tap **Finished** to open an owner-checked bot link and view the exact sent copy.
   For new broadcasts, it replies to the organizer's original message so its quote can
   navigate back to that message. Older broadcasts open the saved sent copy. Telegram's
   public message links support groups/channels, not individual messages in private bot
   chats, so the link uses a bot start parameter instead. Telegram may show **Start**
   before passing that parameter to the bot.

A draft supports up to 2,000 distinct people already registered for this exact form.
Organizers can create 20 drafts and confirm ten messages per hour, with one minute
between confirmations. Limits are transactional. Repeated HTTP requests with the same
request ID and repeated confirmations do not create duplicate audiences or sends.
The audience is a snapshot, excluding future registrations. Drafts/queues expire in 24 hours.

Message content stays in Telegram. The database stores only source references, recipient
IDs, delivery outcomes, and aggregate counts. Thirty days after completion/cancellation,
recipient rows and source references are removed; aggregate statistics remain. This does
not remove Telegram chat history. Links can no longer retrieve the message after its
reference expires or if its saved Telegram copy was deleted. Other organizers cannot
access the audience, draft, or sent-message link.

## Telegram design and delivery

Telegram recommends responsive, accessible, theme-aware interfaces and familiar controls;
it does not prescribe an editable-grid API. The table uses TelegramUI controls, theme/safe
area tokens, keyboard-accessible cells, and contained horizontal scrolling on narrow screens.
The handoff uses `openTelegramLink` and `ForceReply`, with signed Mini App authentication.
Preview preparation preserves text/caption entities and rich blocks, reusing embedded
media by Telegram file ID. The attribution is a literal italic entity or rich paragraph;
form names are never parsed as HTML or Markdown. `copyMessage` delivers the saved preview
without attaching a link to the original message.

One async worker copies confirmed previews at at most ten recipients per second and
spaces messages to one chat by at least 1.1 seconds. Paid broadcasts are disabled.
Telegram 429 responses defer work for the requested duration, with at most five attempts
per recipient. Blocked accounts and rejected copies are failures. Network ambiguity,
server errors, and interrupted in-flight copies are unconfirmed and never automatically
resent: Telegram might have accepted them already. Queue state survives restarts.
No Graph/Bot API call or sleep holds a database transaction. Worker failures feed the
existing administrator monitor. Registration and questionnaires continue independently.

Official references:

- [Mini App design guidelines](https://core.telegram.org/bots/webapps#design-guidelines)
- [Opening Telegram links](https://core.telegram.org/bots/webapps#initializing-mini-apps)
- [Message links and bot deep links](https://core.telegram.org/api/links#message-links)
- [ForceReply](https://core.telegram.org/bots/api#forcereply)
- [copyMessage and native formatting](https://core.telegram.org/bots/api#copymessage)
- [Broadcasting limits](https://core.telegram.org/bots/faq#broadcasting-to-users)
- [Signed authentication](https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app)
