"""Bounded image decoding and normalization for retailer avatars."""
from io import BytesIO
import warnings

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_ICON_BYTES = 1024 * 1024
MAX_ICON_PIXELS = 4_000_000


def normalize_icon(content: bytes) -> bytes:
    if not content or len(content) > MAX_ICON_BYTES:
        raise ValueError('Choose an image no larger than 1 MB.')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(BytesIO(content)) as source:
                if source.format not in {'PNG', 'JPEG', 'WEBP'}:
                    raise ValueError('Choose a PNG, JPEG or WebP image.')
                if source.width * source.height > MAX_ICON_PIXELS:
                    raise ValueError('Choose an image with no more than 4 million pixels.')
                source.load()
                image = ImageOps.exif_transpose(source).convert('RGBA')
                image.thumbnail((128, 128), Image.Resampling.LANCZOS)
                # Copy pixels into a fresh image to omit metadata and trailing content.
                clean = Image.new('RGBA', image.size)
                clean.paste(image)
                output = BytesIO()
                clean.save(output, format='PNG')
                return output.getvalue()
    except (UnidentifiedImageError, OSError, SyntaxError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise ValueError('This image could not be read. Choose a valid PNG, JPEG or WebP image.') from None
