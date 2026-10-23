# Telegram branding assets

- `telegram-avatar.svg`: editable source of the SR monogram.
- `telegram-avatar.jpg`: profile avatar uploaded with `python -m app.bot_profile --apply --photo`.
- `telegram-description.png`: 640 × 360 cover for the bot's description. Upload it
  as a photo through **@BotFather → /mybots → your bot → Edit Bot → Edit Description Picture**.
  This image is independent of the avatar and is not uploaded by `--photo`.
- `telegram-info.png`: dedicated illustration for the `/info` post, sent above the
  project description and WestDevs credits.

## Description cover generation

Created with the built-in `image_gen` tool on 2026-10-22, then exported to the
640 × 360 PNG required by BotFather. It contains no real student information or
functional QR code. It is used only in the Telegram profile, not in the Mini App.

Final generation prompt:

> Create a finished premium editorial illustration for the description cover of the Telegram bot Social Registrar, a student verification and university event registration service at WIUT. This is an illustration asset, not an app screenshot or website mockup. Landscape 16:9 composition, intended export exactly 640 x 360 pixels; keep all important elements well within the frame. Deep midnight navy background (#0d1b34), warm ivory (#fff4d7) and a restrained raspberry burgundy (#b52550) accent, subtle muted blue detail. Sophisticated tactile papercraft / softly lit 3D editorial illustration with crisp silhouettes, generous negative space, elegant academic identity. A warm ivory student identity card, with an abstract faceless avatar and a small burgundy verified check seal, floats gently in the left-center. An ivory event admission pass and a minimal calendar tile sit to the right with a short path of burgundy dots connecting the identity card to the event pass: the visual story is verify once, then join campus events. Tiny tasteful sparkles and understated geometric lines, precise clean composition, beautiful lighting, professional rather than childish. No real personal data. No scannable QR codes, no university crest, no Telegram logo, no captions, no text, no letters, no numbers, no watermark. The image must read clearly at 360px wide in a dark Telegram chat. Use a single coherent restrained scene, not a collage and not overly busy.

## Info cover generation

Created with the built-in `image_gen` tool on 2026-10-23 for the `/info` post.
This separate asset preserves the existing Telegram profile artwork. The scene is
an original stylized illustration, with no real student data or functional QR codes.

Final generation prompt:

```text
Use case: stylized-concept
Asset type: a new premium landscape cover illustration for the Telegram /info post of Social Registrar, a student registration and campus events project by Mukhammadiev Samandar and WestDevs
Primary request: create a beautiful original illustration about students building a connected campus community
Scene: a welcoming miniature campus courtyard at blue hour, with elegant warm ivory architectural arches and a small burgundy stage glowing softly in the background; a handful of small, tasteful, faceless student figures gather and greet one another along a gently curving path
Visual story: the path becomes a single flowing warm-gold ribbon linking a sculptural verified student card and an elegant admission ticket to the campus gathering; objects belong naturally to one cohesive composition
Style: art-directed high-end editorial 3D illustration, matte porcelain and delicate paper textures, beautiful soft shadows, cinematic lighting, sophisticated materials, refined sculptural geometry, warm and human rather than a corporate technology advertisement
Palette: deep midnight navy, warm ivory, restrained raspberry burgundy, subtle soft-gold light, consistent with Social Registrar's existing branding
Composition: wide landscape 16:9, balanced central scene, generous breathing room, clear silhouettes that remain beautiful at 360px chat width, keep all key elements within a safe margin, no tiny clutter
Constraints: no text, letters, numbers, labels, wordmarks, logos, watermark, user interface, readable code, real student data, real or scannable QR codes; all people are stylized and faceless; do not depict an actual university building or invent a university crest; opaque finished background
```
