import json

import pytest

from rag_service.ingestion import prepare


def test_prepare_versions_and_partial_pages(tmp_path):
    source = tmp_path / "source"
    (source / "1").mkdir(parents=True)
    (source / "manifest.json").write_text(
        json.dumps(
            {"sha256": "sourcehash", "pages": [{"page": 1, "status": "completed"}]}
        )
    )
    layout = source / "1" / "layout.json"

    def write(text):
        layout.write_text(json.dumps({"blocks": [{"type": "text", "markdown": text}]}))

    write("1.（单选）题目 A.甲 B.乙【答案】A【解析】甲")
    parents, chunks, assets = prepare(source, tmp_path / "assets", 1)
    again = prepare(source, tmp_path / "assets", 1)
    assert (parents, chunks, assets) == again
    assert all(c["question_version"] == parents[0]["question_version"] for c in chunks)
    assert parents[0]["status"] == "needs_review"
    write("1.（单选）修改题目 A.甲 B.乙【答案】A【解析】甲")
    changed = prepare(source, tmp_path / "assets", 1)
    assert changed[0][0]["question_id"] == parents[0]["question_id"]
    assert changed[0][0]["question_version"] != parents[0]["question_version"]
    with pytest.raises(ValueError):
        prepare(source, tmp_path / "assets", 2)
