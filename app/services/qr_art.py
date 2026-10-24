"""Compose illustrated QR designs and verify the exact exported pixels."""

from colorsys import rgb_to_hls
from io import BytesIO
from warnings import catch_warnings, simplefilter

import segno
import zxingcpp
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps, UnidentifiedImageError
from segno import consts

MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_IMAGE_PIXELS = 4096 * 4096


class QrDesignError(Exception):
    """A safe message suitable for the organizer; never includes provider responses."""


def open_artwork(data: bytes) -> Image.Image:
    if not data or len(data) > MAX_IMAGE_BYTES:
        raise QrDesignError("The image provider returned an invalid image")
    try:
        with catch_warnings():
            simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as image:
                if image.width * image.height > MAX_IMAGE_PIXELS or min(image.size) < 256:
                    raise ValueError
                # Flatten upstream transparency and discard EXIF/other metadata.
                result = Image.new("RGBA", image.size, "white")
                result.alpha_composite(image.convert("RGBA"))
                return result.convert("RGB")
    except (
        OSError,
        ValueError,
        UnidentifiedImageError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ):
        raise QrDesignError("The image provider returned an invalid image") from None


def scan_verified(image: Image.Image, link: str) -> bool:
    """Check the exact URL at print size and phone-preview size, including mild blur."""
    canvas = Image.new("RGBA", image.size, "white")
    canvas.alpha_composite(image.convert("RGBA"))
    flat = canvas.convert("RGB")
    small = flat.resize((300, 300), Image.Resampling.LANCZOS)
    for sample in (flat, small, small.filter(ImageFilter.GaussianBlur(0.45))):
        codes = zxingcpp.read_barcodes(sample, formats=zxingcpp.BarcodeFormat.QRCode)
        if len(codes) != 1 or codes[0].text != link:
            return False
    return True


def _palette(art):
    """Choose actual artwork colors, excluding the illustration's white backdrop."""
    sample = art.resize((96, 96)).quantize(colors=12)
    palette = sample.getpalette()
    colors = []
    for count, index in sample.getcolors():
        color = tuple(palette[index * 3 : index * 3 + 3])
        hue, lightness, saturation = rgb_to_hls(*(value / 255 for value in color))
        if 0.04 < lightness < 0.9:
            colors.append((count, color, hue, saturation))
    if not colors:
        return (30, 39, 48), (66, 78, 92), (248, 249, 250)
    primary = max(colors, key=lambda item: item[0] * (item[3] + 0.1))
    accent = max(
        colors,
        key=lambda item: (
            (min(abs(item[2] - primary[2]), 1 - abs(item[2] - primary[2])) + 0.05)
            * (item[3] + 0.1)
            * item[0] ** 0.5
        ),
    )

    def ink(color, limit):
        luminance = sum(value * weight for value, weight in zip(color, (0.2126, 0.7152, 0.0722)))
        factor = min(1, limit / max(1, luminance))
        return tuple(round(value * factor) for value in color)

    return (
        ink(primary[1], 65),
        ink(accent[1], 95),
        tuple(244 + value * 11 // 255 for value in accent[1]),
    )


def _emblem(art):
    """Remove only border-connected near-white paper, preserving white details."""
    image = ImageOps.contain(art, (512, 512))
    red, green, blue = image.split()
    white = ImageChops.darker(ImageChops.darker(red, green), blue).point(
        lambda value: 255 if value >= 238 else 0
    )
    # An added border joins all background regions without repeated flood fills.
    outside = Image.new("L", (image.width + 2, image.height + 2), 255)
    outside.paste(white, (1, 1))
    ImageDraw.floodfill(outside, (0, 0), 128)
    alpha = outside.crop((1, 1, image.width + 1, image.height + 1)).point(
        lambda value: 0 if value == 128 else 255
    )
    image = image.convert("RGBA")
    image.putalpha(alpha)
    bounds = alpha.getbbox()
    if bounds is None:
        raise QrDesignError(
            "The image provider returned an empty illustration. Try a different prompt"
        )
    if alpha.histogram()[0] < image.width * image.height * 0.08:
        # A full-bleed painting has no removable paper. Keep it intact in a smooth
        # inset rather than punching random white highlights out of the image.
        alpha = Image.new("L", image.size)
        ImageDraw.Draw(alpha).rounded_rectangle(
            (0, 0, image.width - 1, image.height - 1), radius=min(image.size) * 0.14, fill=255
        )
        image.putalpha(alpha)
        return image
    return image.crop(bounds)


def _module_masks(matrix, scale, border, size):
    mask, accents = Image.new("L", (size, size)), Image.new("L", (size, size))
    draw, dots = ImageDraw.Draw(mask), ImageDraw.Draw(accents)
    count = len(matrix)
    for y, row in enumerate(matrix):
        for x, module in enumerate(row):
            if not module >> 8 or module == consts.TYPE_FINDER_PATTERN_DARK:
                continue
            left, top = (x + border) * scale, (y + border) * scale
            rect = (left, top, left + scale - 1, top + scale - 1)
            draw.rectangle(rect, fill=255)
            if module == consts.TYPE_DATA_DARK and not any(
                0 <= nx < count and 0 <= ny < count and matrix[ny][nx] >> 8
                for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1))
            ):
                dots.rectangle(rect, fill=255)
    # Round both convex and concave corners of connected paths. Every occupied
    # cell retains its center; thin strokes and decorative gaps are not invented.
    mask = mask.filter(ImageFilter.GaussianBlur(scale * 0.2)).point(
        lambda value: min(255, max(0, (value - 112) * 16))
    )
    # Smoothing must not bleed even an antialiased pixel into the quiet zone.
    inset = border * scale
    mask = ImageOps.expand(mask.crop((inset, inset, size - inset, size - inset)), border=inset)
    return mask, ImageChops.multiply(mask, accents)


def _eyes(canvas, count, scale, border, primary, accent):
    eye = Image.new("RGBA", (7 * scale, 7 * scale))
    draw = ImageDraw.Draw(eye)
    draw.rounded_rectangle((0, 0, 7 * scale - 1, 7 * scale - 1), radius=1.5 * scale, fill=primary)
    draw.rounded_rectangle(
        (scale, scale, 6 * scale - 1, 6 * scale - 1), radius=0.8 * scale, fill=(0, 0, 0, 0)
    )
    draw.rounded_rectangle(
        (2 * scale, 2 * scale, 5 * scale - 1, 5 * scale - 1), radius=0.8 * scale, fill=accent
    )
    for x, y in ((0, 0), (count - 7, 0), (0, count - 7)):
        canvas.alpha_composite(eye, ((x + border) * scale, (y + border) * scale))


def styled_qr_images(link: str, artwork: bytes) -> dict[bool, bytes]:
    """Return matching backgrounds only after both pass the same bounded scan checks."""
    art = open_artwork(artwork)
    qr = segno.make_qr(link, error="h")
    matrix = list(qr.matrix_iter(border=0, verbose=True))
    count, scale, border = len(matrix), 24, 4
    size = (count + 2 * border) * scale
    primary, accent, paper = _palette(art)
    texture = ImageOps.fit(art, (size, size), method=Image.Resampling.LANCZOS)
    background = Image.blend(
        Image.new("RGB", (size, size), paper),
        texture.filter(ImageFilter.GaussianBlur(size * 0.035)),
        0.06,
    ).convert("RGBA")
    mask, accents = _module_masks(matrix, scale, border, size)
    ink = ImageOps.colorize(
        ImageOps.grayscale(texture),
        tuple(round(value * 0.8) for value in primary),
        tuple(min(140, round(value * 1.2)) for value in primary),
    ).convert("RGBA")
    bases = {}
    for transparent in (True, False):
        canvas = Image.new("RGBA", (size, size)) if transparent else background.copy()
        canvas.paste(ink, mask=mask)
        canvas.paste(accent, mask=accents)
        _eyes(canvas, count, scale, border, primary, accent)
        bases[transparent] = canvas
    emblem = _emblem(art)
    # Center artwork intentionally uses part of H-level error correction. Finder,
    # timing, format/version areas and the four-cell margin stay outside this box.
    # Prefer the most expressive size which scans in BOTH backgrounds. These are
    # local layout attempts, never additional provider requests or a plain fallback.
    for fraction in (0.38, 0.32, 0.26, 0.20):
        width = min(round(count * fraction), count - 19) * scale
        subject = ImageOps.contain(emblem, (width, width), method=Image.Resampling.LANCZOS)
        position = ((size - subject.width) // 2, (size - subject.height) // 2)
        # Dilation is limited to the subject's small box, not the whole PNG.
        clearance = ImageOps.expand(subject.getchannel("A"), border=scale).filter(
            ImageFilter.MaxFilter(scale + 1)
        )
        box = (position[0] - scale, position[1] - scale)
        candidates = {}
        for transparent, base in bases.items():
            canvas = base.copy()
            paper_crop = background.crop(
                (*box, box[0] + clearance.width, box[1] + clearance.height)
            )
            canvas.paste((0, 0, 0, 0) if transparent else paper_crop, box, clearance)
            canvas.alpha_composite(subject, position)
            candidates[transparent] = canvas
        if all(scan_verified(canvas, link) for canvas in candidates.values()):
            images = {}
            for transparent, canvas in candidates.items():
                result = BytesIO()
                (canvas if transparent else canvas.convert("RGB")).save(result, format="PNG")
                images[transparent] = result.getvalue()
            return images
    raise QrDesignError("This design did not pass the scan check. Please try a different prompt")
