import pytest
from PIL import Image

from rag_service.assets import asset_path, crop_asset


def test_crop_stable_and_safe(tmp_path):
    source = tmp_path / "page.png"
    Image.new("RGB", (100, 200), "red").save(source)
    first = crop_asset(source, [0, 0, 500, 500], tmp_path / "assets")
    second = crop_asset(source, [0, 0, 500, 500], tmp_path / "assets")
    assert first == second
    assert Image.open(asset_path(tmp_path / "assets", first)).size == (50, 100)
    with pytest.raises(ValueError):
        asset_path(tmp_path, "../secret")
    with pytest.raises(ValueError):
        crop_asset(source, [500, 0, 0, 200], tmp_path)
