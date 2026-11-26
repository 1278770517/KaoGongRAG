"""导入时裁剪图片并按内容哈希存储；请求时只按资源 ID 读取独立 PNG。"""

import hashlib
import io
import math
import re
import tempfile
from pathlib import Path

from PIL import Image


def asset_path(root: Path, asset_id: str) -> Path:
    """只接受哈希形式的资源 ID，避免将用户输入当作任意文件路径。"""
    if not re.fullmatch(r"[0-9a-f]{64}", asset_id):
        raise ValueError("Invalid asset id")
    return root / f"{asset_id}.png"


def crop_asset(source: Path, bbox: list[float], root: Path) -> str:
    """将 0..1000 布局坐标换算为像素并裁剪，按 PNG 内容哈希复用资源。"""
    if len(bbox) != 4 or not all(math.isfinite(x) and 0 <= x <= 1000 for x in bbox):
        raise ValueError("Invalid normalized bbox")
    x1, y1, x2, y2 = bbox
    if x1 >= x2 or y1 >= y2:
        raise ValueError("Empty bbox")
    with Image.open(source) as image:
        w, h = image.size
        pixels = (
            math.floor(x1 * w / 1000),
            math.floor(y1 * h / 1000),
            math.ceil(x2 * w / 1000),
            math.ceil(y2 * h / 1000),
        )
        output = io.BytesIO()
        image.crop(pixels).save(output, format="PNG")
    data = output.getvalue()
    asset_id = hashlib.sha256(data).hexdigest()
    root.mkdir(parents=True, exist_ok=True)
    path = asset_path(root, asset_id)
    if not path.exists():
        # Worker writes before staging SQL references; readers cannot observe partial files.
        with tempfile.NamedTemporaryFile(
            dir=root, suffix=".tmp", delete=False
        ) as handle:
            handle.write(data)
            temporary = Path(handle.name)
        temporary.replace(path)
    return asset_id
