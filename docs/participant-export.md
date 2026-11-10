# Participant workbook format

The `.xlsx` file is both a readable participant table and a versioned data exchange
format. It contains three visible worksheets. No macros, network connections, hidden
worksheets, or external links are needed to read it.

## Reading the file

**Participants** opens first, with the usual contacts, education level, responses and
organizer columns. Technical columns at the right are hidden by default. They belong
to the same Excel table, so sorting the table keeps IDs with the correct person.
Use Excel/LibreOffice's **Unhide columns** to inspect them. Hidden columns are for
presentation only; every application reading the workbook can access their contents.

**Export info** is a Key/Value/Description table. It includes the form UUID and name,
department, organizer's Telegram ID, creation time, form/column revisions, file UUID,
generation time in UTC, export scope and number of exported participants.

**Columns** maps every participant column to a stable key, source ID, data type and
encoding. It includes choice options and whether the column is hidden. Renaming a
question or changing column order does not change that question's source ID/key.

## Version 1 contract

Read the following entries from `Export info` by **Key**, without relying on row order:

| Key | Value/type | Meaning |
| --- | --- | --- |
| `format` | `wiut-social-registrar.participants` | File format identifier |
| `schema_version` | Integer `1` | Import contract version |
| `export_id` | UUID text | A new ID for each generated workbook |
| `exported_at_utc` | ISO 8601 text ending in `Z` | File generation time, not a live synchronization cursor |
| `source` | `WIUT Social Registrar` | Producer name |
| `event_id` | UUID text | Stable form/event identity |
| `event_title` | Text | Form name at export time |
| `department` | Text or blank | Organizer's department |
| `organizer_telegram_id` | Decimal ID as text | Form owner's Telegram user ID |
| `event_created_at_utc` | ISO 8601 UTC text | Form creation time |
| `event_revision` | Integer | Settings revision |
| `form_revision` | Integer | Question definition revision |
| `columns_revision` | Integer | Organizer column definition revision |
| `export_scope` | `selected` or `all` | Checked participants or legacy full-form export |
| `participant_count` | Integer | Actual exported data rows, excluding the header |
| `participants_sheet` | `Participants` | Worksheet containing records |
| `columns_sheet` | `Columns` | Worksheet containing field definitions |
| `participant_key` | `event_id + system:telegram_id` | Stable identity pair for a record |
| `technical_columns` | Text | Instructions for showing the hidden columns |

The `Columns` header row defines these fields:

| Header | Meaning |
| --- | --- |
| `Column` | Excel column letter at generation time, for convenient inspection |
| `Header` | Exact, unique header in Participants; use it to find cells after column reordering |
| `Key` | Stable semantic key, unique within this workbook |
| `Scope` | `contact`, `answer`, `column`, `system`, or a display-only scope |
| `Field ID` | Source field name, question UUID, or organizer column UUID |
| `Type` | `text`, `number`, `date`, `checkbox`, `single_choice`, `multiple_choice`, or `utc_datetime` |
| `Encoding` | How the cell represents that type, as described below |
| `Hidden` | Boolean; presentation only, not an access restriction |
| `Options JSON` | JSON array of choice labels, or blank for non-choice fields |
| `Required` | Question's Boolean required flag; blank for other fields |

### Stable keys

- `contact:student_id`, `contact:name`, `contact:telegram`, `contact:email`,
  `contact:phone_number`, `contact:education_level` identify the visible profile fields
- `answer:<question UUID>` identifies the exact current answer
- `column:<column UUID>` identifies an organizer-defined value
- `system:telegram_id` is the Telegram user ID as **text**, even when a username exists
- `system:registration_id` is the internal attendance row ID as **text**; it is local
  to this installation and must not be used as a global participant identity
- `system:registered_at_utc` is the attendance time as ISO 8601 UTC text
- `system:row_revision` is the attendance row's edit revision as an Excel number

Multiple-choice answers have two columns: `display:answer:<UUID>` contains the readable
newline-joined labels (`Scope=answer_display`), while the hidden `answer:<UUID>` contains
the exact JSON array. **Import the JSON column**: option labels can themselves contain
newlines. The visible choice cells are for display only. Legacy multiple selections
remain intact. A blank JSON cell means no current answer; it is not the string `null`.

Technical headers start with `_sr_`. A user label matching a reserved header receives
a unique suffix, just like other duplicate labels. Stable keys and source IDs remain
unchanged. All technical columns are part of the Participants table and are hidden,
including exact JSON choice columns; the two explanatory worksheets remain visible.

### Encodings

| Encoding | Cell representation |
| --- | --- |
| `text` | Literal string; blank means no value. Preserve IDs, phone prefixes and leading zeroes |
| `number_or_text` | Excel number when precision permits, otherwise literal decimal text; do not round large values |
| `excel_date` | Excel date cell with `yyyy-mm-dd` display; read as a date, without a time zone |
| `boolean` | Excel Boolean; distinguish `FALSE` from a blank cell |
| `iso8601` | UTC date/time text ending in `Z` |
| `json` | Exact choice-label array encoded as JSON, or blank for no current answer |
| `lines` | Display-only newline-joined choice labels; import the corresponding JSON field |

## Import guidance

1. Confirm `format` and supported `schema_version`. Files from before this contract
   lack these entries; do not guess their event identity from a title or filename.
2. Read `Columns`, verify unique keys/headers, then resolve its exact **Header** values
   against Participants. Column letters and row positions are not record identities.
3. Read all Participants data rows, including hidden cells. Check the declared count
   and the presence of nonempty, unique `system:telegram_id` values within the file.
4. Identify attendance by `(event_id, system:telegram_id)`. Keep Telegram IDs as strings
   or arbitrary-precision integers; usernames and display names can change. Student ID
   remains available as the university identifier, with leading zeroes preserved.
5. Use `export_id` to detect the same file being forwarded again. A new export of the
   same event has a new file ID and may contain updated values or a different selection.
   An absent participant in a selected export does not imply their attendance was deleted.
6. Treat imported content and metadata as user-supplied data, not proof of authenticity
   or permission to contact people. Authorization belongs to the receiving bot.

Unknown additive metadata/columns may be ignored. Breaking changes to key meanings,
encodings or required structure must increment `schema_version`. This document and
`app/services/participant_export_schema.py` define the current contract.

Expired answers/organizer values are blank in both their visible and technical cells;
they are never reconstructed from old data. Exported files are independent snapshots,
so the server cannot refresh or delete answers in a file already sent to a chat.
