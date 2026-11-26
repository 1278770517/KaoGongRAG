import base64
import io
import math
from typing import Annotated, Literal

from PIL import Image
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator


class TextBlock(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    type: Literal["text"]
    markdown: str = Field(validation_alias=AliasChoices("markdown", "text"))


class ImageBlock(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    type: Literal["image"]
    bbox: list[float] = Field(min_length=4, max_length=4)
    alt: str = "图片"

    @model_validator(mode="after")
    def valid_bbox(self):
        x1, y1, x2, y2 = self.bbox
        if not all(math.isfinite(v) and 0 <= v <= 1000 for v in self.bbox):
            raise ValueError("bbox coordinates must be finite and within 0..1000")
        if x1 >= x2 or y1 >= y2:
            raise ValueError("bbox must have positive width and height")
        return self


class Layout(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    blocks: list[Annotated[TextBlock | ImageBlock, Field(discriminator="type")]]


def parse_layout(text: str) -> Layout:
    text = text.strip()
    # 兼容模型在 JSON 外层加 Markdown 代码围栏的情况。
    if text.startswith(("```json\n", "```\n")):
        if not text.endswith("```"):
            raise ValueError("Unclosed JSON fence")
        text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    return Layout.model_validate_json(text)


def render_markdown(layout: Layout, png: bytes) -> str:
    parts = []
    with Image.open(io.BytesIO(png)) as page:
        # 按模型给出的阅读顺序遍历，插图保留在相邻正文之间。
        for block in layout.blocks:
            if isinstance(block, TextBlock):
                parts.append(block.markdown.strip())
                continue
            x1, y1, x2, y2 = block.bbox
            # 将 0–1000 的归一化坐标换算成像素，向外取整以保留边缘。
            bounds = (
                math.floor(x1 * page.width / 1000),
                math.floor(y1 * page.height / 1000),
                math.ceil(x2 * page.width / 1000),
                math.ceil(y2 * page.height / 1000),
            )
            image = io.BytesIO()
            page.crop(bounds).save(image, format="PNG")
            # 用 data URL 将裁出的 PNG 直接写入 Markdown。
            encoded = base64.b64encode(image.getvalue()).decode("ascii")
            alt = (
                block.alt.replace("\\", "\\\\")
                .replace("[", "\\[")
                .replace("]", "\\]")
                .replace("\n", " ")
                .replace("\r", " ")
            )
            parts.append(f"![{alt}](data:image/png;base64,{encoded})")
    return "\n\n".join(p for p in parts if p)
