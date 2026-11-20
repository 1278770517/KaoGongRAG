import base64
import io
import json

import httpx
import pymupdf
import pytest
from PIL import Image

from pdf_ocr.client import OCRClient, OCRError
from pdf_ocr.config import Settings
from pdf_ocr.converter import convert_pdf
from pdf_ocr.layout import parse_layout, render_markdown


def page_png():
    image = Image.new("RGB", (100, 200), "red")
    data = io.BytesIO()
    image.save(data, format="PNG")
    return data.getvalue()


def test_live_model_text_field_alias():
    layout = parse_layout('{"blocks":[{"type":"text","text":"5. SECOND PAGE"}]}')
    assert render_markdown(layout, page_png()) == "5. SECOND PAGE"


def test_null_choice_is_sanitized():
    with (
        httpx.Client(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(200, json={"output": {"choices": [None]}})
            )
        ) as http,
        pytest.raises(OCRError),
    ):
        OCRClient(settings(ocr_retries=0), http=http).recognize(page_png())


def test_settings_env_file_and_process_precedence(tmp_path, monkeypatch):
    monkeypatch.delenv("OCR_API_KEY", raising=False)
    config = tmp_path / ".env"
    config.write_text("OCR_API_KEY=file-key\nOCR_DPI=100\n", encoding="utf-8")
    assert Settings(_env_file=config).ocr_api_key.get_secret_value() == "file-key"
    monkeypatch.setenv("OCR_API_KEY", "process-key")
    assert Settings(_env_file=config).ocr_api_key.get_secret_value() == "process-key"
    assert Settings(_env_file=config).ocr_max_tokens == 4096


def test_reading_order_and_real_base64_crop():
    layout = parse_layout(
        json.dumps(
            {
                "blocks": [
                    {"type": "text", "markdown": "左栏末尾"},
                    {"type": "image", "bbox": [0, 0, 500, 500], "alt": "图 [1]"},
                    {"type": "text", "markdown": "右栏开头"},
                ]
            }
        )
    )
    md = render_markdown(layout, page_png())
    assert (
        md.index("左栏末尾") < md.index("data:image/png;base64,") < md.index("右栏开头")
    )
    encoded = md.split("base64,")[1].split(")")[0]
    crop = Image.open(io.BytesIO(base64.b64decode(encoded, validate=True)))
    assert crop.size == (50, 100)
    assert crop.getpixel((0, 0)) == (255, 0, 0)


@pytest.mark.parametrize(
    "bbox",
    [[0, 0, 0, 100], [-1, 0, 100, 100], [0, 0, 1001, 100], [0, 0, float("nan"), 100]],
)
def test_reject_invalid_image_coordinates(bbox):
    with pytest.raises(ValueError):
        parse_layout(json.dumps({"blocks": [{"type": "image", "bbox": bbox}]}))


def test_blank_page_and_fenced_json():
    layout = parse_layout('```json\n{"blocks": []}\n```')
    assert render_markdown(layout, page_png()) == ""


def make_pdf(path):
    with pymupdf.open() as doc:
        for number in range(3):
            page = doc.new_page(width=100, height=200)
            page.insert_text((10, 30), f"Page {number + 1}")
            if number == 1:
                page.set_rotation(90)
        doc.save(path)


class FakeOCR:
    def recognize(self, png):
        image = Image.open(io.BytesIO(png))
        return parse_layout(
            json.dumps(
                {
                    "blocks": [
                        {"type": "text", "markdown": f"{image.width}x{image.height}"}
                    ]
                }
            )
        )


def test_selected_pages_keep_original_page_numbers_and_rotation(tmp_path):
    source = tmp_path / "试卷.pdf"
    make_pdf(source)
    result = convert_pdf(
        source, tmp_path / "output", FakeOCR(), start_page=2, end_page=3, dpi=72
    )
    root = tmp_path / "output" / "试卷"
    assert (root / "2" / "2.md").read_text(encoding="utf-8").strip() == "200x100"
    assert (root / "3" / "3.md").is_file()
    assert not (root / "1").exists()
    assert result["status"] == "completed"
    assert [p["page"] for p in result["pages"]] == [2, 3]
    with pytest.raises(FileExistsError):
        convert_pdf(source, tmp_path / "output", FakeOCR())


def test_failed_page_does_not_stop_following_pages(tmp_path):
    source = tmp_path / "test.pdf"
    make_pdf(source)

    class FailingOCR(FakeOCR):
        calls = 0

        def recognize(self, png):
            self.calls += 1
            if self.calls == 2:
                raise OCRError("invalid response")
            return super().recognize(png)

    result = convert_pdf(source, tmp_path / "output", FailingOCR(), dpi=72)
    assert result["status"] == "partial_failure"
    assert [p["status"] for p in result["pages"]] == [
        "completed",
        "failed",
        "completed",
    ]
    assert not (tmp_path / "output/test/2/2.md").exists()
    assert (
        json.loads((tmp_path / "output/test/manifest.json").read_text(encoding="utf-8"))
        == result
    )


def test_invalid_page_range_creates_no_output(tmp_path):
    source = tmp_path / "test.pdf"
    make_pdf(source)
    with pytest.raises(ValueError):
        convert_pdf(source, tmp_path / "output", FakeOCR(), start_page=0)
    assert not (tmp_path / "output").exists()


def test_converter_embeds_image_in_numbered_markdown(tmp_path):
    source = tmp_path / "image.pdf"
    make_pdf(source)

    class ImageOCR:
        def recognize(self, png):
            return parse_layout(
                '{"blocks":[{"type":"text","markdown":"before"},{"type":"image","bbox":[0,0,500,500]},{"type":"text","markdown":"after"}]}'
            )

    convert_pdf(source, tmp_path / "output", ImageOCR(), end_page=1, dpi=72)
    md = (tmp_path / "output/image/1/1.md").read_text(encoding="utf-8")
    assert md.index("before") < md.index("data:image/png;base64,") < md.index("after")
    crop = Image.open(
        io.BytesIO(base64.b64decode(md.split("base64,")[1].split(")")[0]))
    )
    assert crop.size == (50, 100)


@pytest.mark.parametrize(
    ("status", "expected"), [("completed", 0), ("partial_failure", 1)]
)
def test_cli_exit_codes(tmp_path, monkeypatch, status, expected):
    import main

    monkeypatch.setenv("OCR_API_KEY", "test-key")
    monkeypatch.setattr(main, "convert_pdf", lambda *a, **kw: {"status": status})
    assert (
        main.main(["unused.pdf", "--env-file", str(tmp_path / "missing.env")])
        == expected
    )


def test_cli_invalid_config_does_not_expose_key(tmp_path, monkeypatch, capsys):
    import main

    monkeypatch.setenv("OCR_API_KEY", "test-secret-value")
    monkeypatch.setenv("OCR_DPI", "bad")
    assert main.main(["unused.pdf", "--env-file", str(tmp_path / "missing.env")]) == 2
    assert "test-secret-value" not in capsys.readouterr().err


def settings(**kwargs):
    return Settings(_env_file=None, ocr_api_key="test-key", **kwargs)


def test_http_retry_and_schema():
    requests = []

    def handler(request):
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(503)
        return httpx.Response(
            200,
            json={
                "output": {
                    "choices": [
                        {
                            "finish_reason": "stop",
                            "message": {"content": [{"text": '{"blocks": []}'}]},
                        }
                    ]
                }
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        client = OCRClient(settings(ocr_retries=1), http=http, sleep=lambda _: None)
        assert client.recognize(page_png()).blocks == []
    body = json.loads(requests[-1].content)
    assert body["input"]["messages"][0]["content"][0]["image"].startswith(
        "data:image/png;base64,"
    )
    assert requests[-1].headers["authorization"] == "Bearer test-key"


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(401, text="secret should not be logged"),
        httpx.Response(
            200,
            json={
                "output": {
                    "choices": [
                        {
                            "finish_reason": "length",
                            "message": {"content": [{"text": '{"blocks": []}'}]},
                        }
                    ]
                }
            },
        ),
        httpx.Response(
            200,
            json={
                "output": {
                    "choices": [
                        {
                            "finish_reason": "stop",
                            "message": {"content": [{"text": "not JSON"}]},
                        }
                    ]
                }
            },
        ),
    ],
)
def test_bad_response_is_not_success(response):
    with (
        httpx.Client(transport=httpx.MockTransport(lambda _: response)) as http,
        pytest.raises(OCRError) as error,
    ):
        OCRClient(settings(ocr_retries=0), http=http).recognize(page_png())
    assert "secret" not in str(error.value)
