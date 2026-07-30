import io

from PIL import Image, ImageDraw

from cloud.mapping_and_notification.ai.wall_detection import WallDetector, WallDetectionCache


def test_wall_grid_contract_and_cache():
    image = Image.new("RGB", (32, 16), "white")
    ImageDraw.Draw(image).rectangle((0, 0, 2, 15), fill="black")
    output = io.BytesIO(); image.save(output, format="PNG")
    cached = WallDetectionCache()
    first = cached.get_or_detect(output.getvalue(), canvas_width=16, canvas_height=8, grid_scale=8)
    second = cached.get_or_detect(output.getvalue(), canvas_width=16, canvas_height=8, grid_scale=8)
    assert first is second
    assert first["status"] == "success"
    assert first["wallGrid"] == first["grid"]
    assert len(first["grid"]) == 1 and len(first["grid"][0]) == 2
