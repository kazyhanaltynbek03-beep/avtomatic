import json

import pytest
from fastapi import HTTPException

from app import ai


def test_product_draft_returns_editable_copy_and_questions(monkeypatch):
    monkeypatch.setattr(ai, "call_response", lambda *args, **kwargs: {
        "output": [{"content": [{"type": "output_text", "text": json.dumps({
            "name": "Термокружка 450 мл", "description": "Термокружка для напитков.",
            "specifications": [{"name": "Объём", "value": "450 мл"}],
            "questions": ["Уточните материал корпуса"],
        }, ensure_ascii=False)}]}]
    })

    result = ai.product_draft({"facts": "Термокружка, объём 450 мл"})

    assert result["name"] == "Термокружка 450 мл"
    assert result["specifications"] == {"Объём": "450 мл"}
    assert result["questions"] == ["Уточните материал корпуса"]
    assert result["status"] == "draft_requires_review"
    assert "price" not in result and "purchase_cost" not in result


def test_product_draft_requires_confirmed_input():
    with pytest.raises(HTTPException) as exc:
        ai.product_draft({"facts": "  "})
    assert exc.value.status_code == 422
