import pytest
from fastapi import HTTPException

from app import ai


def test_model_catalog_exposes_only_server_allowlisted_models(monkeypatch):
    monkeypatch.setenv("OPENAI_MODEL", "gpt-default")
    monkeypatch.setenv("OPENAI_ALLOWED_MODELS", "gpt-fast, gpt-quality,gpt-fast")

    catalog = ai.model_catalog()

    assert catalog["default"] == "gpt-default"
    assert [item["id"] for item in catalog["items"]] == [
        "gpt-default", "gpt-fast", "gpt-quality"
    ]
    assert ai.selected_model("gpt-quality") == "gpt-quality"


def test_model_selection_rejects_unconfigured_models(monkeypatch):
    monkeypatch.setenv("OPENAI_MODEL", "gpt-default")
    monkeypatch.setenv("OPENAI_ALLOWED_MODELS", "gpt-fast")

    with pytest.raises(HTTPException) as error:
        ai.selected_model("arbitrary-client-model")

    assert error.value.status_code == 422
