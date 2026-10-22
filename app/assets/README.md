# Telegram branding assets

- `telegram-avatar.svg`: editable source of the SR monogram.
- `telegram-avatar.jpg`: profile avatar uploaded with `python -m app.bot_profile --apply --photo`.
- `telegram-description.png`: 640 × 360 cover for the bot's description. Upload it
  as a photo through **@BotFather → /mybots → your bot → Edit Bot → Edit Description Picture**.
  This image is independent of the avatar and is not uploaded by `--photo`.

## Description cover generation

Created with the built-in `image_gen` tool on 2026-10-22, then exported to the
640 × 360 PNG required by BotFather. It contains no real student information or
functional QR code. It is used only in the Telegram profile, not in the Mini App.

Final generation prompt:

> Create a finished premium editorial illustration for the description cover of the Telegram bot Social Registrar, a student verification and university event registration service at WIUT. This is an illustration asset, not an app screenshot or website mockup. Landscape 16:9 composition, intended export exactly 640 x 360 pixels; keep all important elements well within the frame. Deep midnight navy background (#0d1b34), warm ivory (#fff4d7) and a restrained raspberry burgundy (#b52550) accent, subtle muted blue detail. Sophisticated tactile papercraft / softly lit 3D editorial illustration with crisp silhouettes, generous negative space, elegant academic identity. A warm ivory student identity card, with an abstract faceless avatar and a small burgundy verified check seal, floats gently in the left-center. An ivory event admission pass and a minimal calendar tile sit to the right with a short path of burgundy dots connecting the identity card to the event pass: the visual story is verify once, then join campus events. Tiny tasteful sparkles and understated geometric lines, precise clean composition, beautiful lighting, professional rather than childish. No real personal data. No scannable QR codes, no university crest, no Telegram logo, no captions, no text, no letters, no numbers, no watermark. The image must read clearly at 360px wide in a dark Telegram chat. Use a single coherent restrained scene, not a collage and not overly busy.
