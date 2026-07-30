"""Private Pillow route renderer; output is an opaque storage object, never a URL."""

from __future__ import annotations

import io
from PIL import Image, ImageDraw


def render_route(image_bytes: bytes, route: dict, *, width: int = 800, height: int = 600) -> bytes:
    image = Image.open(io.BytesIO(image_bytes)).convert("RGBA")
    image.thumbnail((width, height))
    canvas = Image.new("RGBA", (width, height), "#f1f5f9")
    canvas.alpha_composite(image, ((width - image.width) // 2, (height - image.height) // 2))
    draw = ImageDraw.Draw(canvas, "RGBA")
    points = [(float(n.get("coord_x", 0)), float(n.get("coord_y", 0))) for n in route.get("path", [])]
    if len(points) > 1:
        draw.line(points, fill=(20, 184, 166, 230), width=5, joint="curve")
    for index, point in enumerate(points):
        colour = (245, 158, 11, 255) if index == len(points) - 1 else (20, 184, 166, 255)
        draw.ellipse((point[0] - 8, point[1] - 8, point[0] + 8, point[1] + 8), fill=colour, outline=(255, 255, 255, 230), width=2)
    output = io.BytesIO()
    canvas.convert("RGB").save(output, format="PNG")
    return output.getvalue()
