from pathlib import Path


def test_runtime_has_no_legacy_marketplace_env_credentials():
    app_dir = Path(__file__).resolve().parents[1] / "app"
    forbidden = ("WB_MAIN_TOKEN", "KASPI_MAIN_TOKEN", "OZON_MAIN_TOKEN")
    offenders = []
    for path in app_dir.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for token in forbidden:
            if token in text:
                offenders.append(f"{path.name}:{token}")
    assert not offenders, f"Legacy marketplace ENV credential references found: {offenders}"
