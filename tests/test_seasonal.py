from __future__ import annotations

import json
import shutil

import pytest

from app import create_app
from app import seasonal
from app.steps.load_page import FetchError


@pytest.fixture()
def seasonal_app(tmp_path):
    site = tmp_path / "site"
    original = tmp_path / "original"
    shutil.copytree(seasonal.DEFAULT_ORIGINAL_DIR, original)
    shutil.copytree(seasonal.DEFAULT_ORIGINAL_DIR, site)
    app = create_app({
        "TESTING": True,
        "PROVIDER": "fake",
        "FALLBACK_PROVIDER": "none",
        "SEASONAL_SITE_DIR": str(site),
        "SEASONAL_ORIGINAL_DIR": str(original),
    })
    return app


@pytest.fixture()
def client(seasonal_app):
    return seasonal_app.test_client()


def test_page_has_banner_toggles_reset_and_history_controls(client):
    response = client.get("/seasonal")
    assert response.status_code == 200
    page = response.get_data(as_text=True)
    assert "Proof of concept demo: seasonal redesigns are triggered by toggles here." in page
    for preset in ("Christmas", "Halloween", "Workers", "Children", "Eid al-Fitr (Sallah)"):
        assert preset in page
    assert "Enter your own season" in page
    assert "Reset to original" in page
    assert 'id="back-button"' in page
    assert 'id="forward-button"' in page
    assert "/seasonal/preview" in page


def test_banner_stays_visible_after_redesign(client):
    assert client.post("/seasonal/api/redesign", json={"season": "Halloween"}).status_code == 200
    page = client.get("/seasonal").get_data(as_text=True)
    assert "Proof of concept demo: seasonal redesigns are triggered by toggles here." in page


def test_redesign_replaces_current_season(client):
    assert client.post("/seasonal/api/redesign", json={"season": "Christmas"}).status_code == 200
    preview = client.get("/seasonal/preview").get_data(as_text=True)
    assert "Sample Caf" in preview and "Christmas" in preview

    body = client.post("/seasonal/api/redesign", json={"season": "Halloween"}).get_json()
    assert body["season"] == "Halloween"
    preview = client.get("/seasonal/preview").get_data(as_text=True)
    assert "Halloween" in preview
    assert "Christmas" not in preview


def test_custom_season_input(client):
    body = client.post(
        "/seasonal/api/redesign", json={"season": "Cherry Blossom Festival"}
    ).get_json()
    assert body["season"] == "Cherry Blossom Festival"
    preview = client.get("/seasonal/preview").get_data(as_text=True)
    assert "Cherry Blossom Festival" in preview


def test_empty_season_keeps_previous_version(client):
    before = client.get("/seasonal/preview").get_data(as_text=True)
    response = client.post("/seasonal/api/redesign", json={"season": "   "})
    assert response.status_code == 400
    assert "error" in response.get_json()
    assert client.get("/seasonal/preview").get_data(as_text=True) == before


def test_history_steps_back_and_forward(client):
    client.post("/seasonal/api/redesign", json={"season": "Christmas"})
    client.post("/seasonal/api/redesign", json={"season": "Halloween"})
    state = client.get("/seasonal/api/state").get_json()
    assert state["history"] == ["Original", "Christmas", "Halloween"]

    assert client.post("/seasonal/api/back").get_json()["season"] == "Christmas"
    assert "Christmas" in client.get("/seasonal/preview").get_data(as_text=True)
    assert client.post("/seasonal/api/back").get_json()["season"] == "Original"
    assert client.post("/seasonal/api/forward").get_json()["season"] == "Christmas"


def test_history_is_capped(client):
    for number in range(7):
        client.post("/seasonal/api/redesign", json={"season": f"Season {number}"})
    state = client.get("/seasonal/api/state").get_json()
    assert len(state["history"]) == seasonal.HISTORY_LIMIT
    assert state["season"] == "Season 6"


def test_reset_restores_original(client, seasonal_app):
    client.post("/seasonal/api/redesign", json={"season": "Christmas"})
    body = client.post("/seasonal/api/reset").get_json()
    assert body["season"] == "Original"
    assert body["history"] == ["Original"]
    site_files = seasonal.read_files(seasonal.site_dir(seasonal_app.config))
    original_files = seasonal.read_files(seasonal.original_dir(seasonal_app.config))
    assert site_files == original_files


def test_all_preset_designs_and_custom_design_pass_validation():
    for name in (*seasonal.PRESET_SEASONS, "Cherry Blossom Festival", "Sallah", "Xmas!!!"):
        seasonal.validate_files(seasonal.design_locally(name))


def test_validation_rejects_broken_or_incomplete_agent_output():
    good = seasonal.design_locally("Christmas")

    broken_html = dict(good)
    broken_html["index.html"] = "<!doctype html><html><body><p>no sections</p></body></html>"
    with pytest.raises(seasonal.ValidationError):
        seasonal.validate_files(broken_html)

    broken_css = dict(good)
    broken_css["style.css"] = "body { color: red;"
    with pytest.raises(seasonal.ValidationError):
        seasonal.validate_files(broken_css)

    broken_js = dict(good)
    broken_js["script.js"] = "function oops( { var x = 1;"
    with pytest.raises(seasonal.ValidationError):
        seasonal.validate_files(broken_js)

    with pytest.raises(seasonal.ValidationError):
        seasonal.validate_files({"index.html": good["index.html"]})


def test_agent_cannot_write_outside_site_folder(seasonal_app):
    config = seasonal_app.config
    with pytest.raises(seasonal.SeasonalError):
        seasonal.resolve_site_path(config, "../app.py")
    with pytest.raises(seasonal.SeasonalError):
        seasonal.resolve_site_path(config, "/etc/passwd")
    files = dict(seasonal.design_locally("Eid al-Fitr (Sallah)"))
    files["../../evil.html"] = "evil"
    seasonal.write_files(config, files)  # unknown names are dropped
    assert not (seasonal.ROOT / "evil.html").exists()


def test_agent_prompt_contains_instruction_season_and_source():
    current = seasonal.design_locally("Original")
    prompt = seasonal.build_agent_prompt("Halloween", current)
    assert "Redesign this website for the season: Halloween." in prompt
    assert "Keep the navigation and all sections" in prompt
    assert current["index.html"] in prompt
    assert current["style.css"] in prompt
    assert current["script.js"] in prompt


def _llm_client(tmp_path, monkeypatch, complete):
    site = tmp_path / "site"
    original = tmp_path / "original"
    shutil.copytree(seasonal.DEFAULT_ORIGINAL_DIR, original)
    shutil.copytree(seasonal.DEFAULT_ORIGINAL_DIR, site)
    app = create_app({
        "TESTING": True,
        "PROVIDER": "openai_compat",
        "PROVIDER_BASE_URL": "http://localhost:1",
        "MODEL_NAME": "test-model",
        "FALLBACK_PROVIDER": "none",
        "SEASONAL_SITE_DIR": str(site),
        "SEASONAL_ORIGINAL_DIR": str(original),
    })
    monkeypatch.setattr(seasonal.openai_compat, "complete", complete)
    return app.test_client()


def test_llm_success_uses_returned_files(tmp_path, monkeypatch):
    seen = {}

    def fake_complete(prompt, **kwargs):
        seen["prompt"] = prompt
        files = seasonal.design_locally("Christmas")
        files["index.html"] = files["index.html"].replace(
            "Sample Café at Christmas (sample text)", "LLM Marker Heading (sample text)"
        )
        return json.dumps(files)

    client = _llm_client(tmp_path, monkeypatch, fake_complete)
    body = client.post("/seasonal/api/redesign", json={"season": "Christmas"}).get_json()
    assert body["season"] == "Christmas"
    assert not body.get("warning")
    assert "LLM Marker Heading" in client.get("/seasonal/preview").get_data(as_text=True)
    assert "Redesign this website for the season: Christmas." in seen["prompt"]
    assert "Current site source files:" in seen["prompt"]


def test_llm_unreachable_falls_back_to_builtin_with_warning(tmp_path, monkeypatch):
    def failing_complete(prompt, **kwargs):
        raise FetchError("AI provider could not be reached before the timeout.")

    client = _llm_client(tmp_path, monkeypatch, failing_complete)
    response = client.post("/seasonal/api/redesign", json={"season": "Christmas"})
    assert response.status_code == 200
    body = response.get_json()
    assert "built-in designer" in body.get("warning", "")
    assert "Christmas" in client.get("/seasonal/preview").get_data(as_text=True)


def test_llm_invalid_output_keeps_previous_version(tmp_path, monkeypatch):
    client = _llm_client(tmp_path, monkeypatch, lambda prompt, **kwargs: "not json at all")
    before = client.get("/seasonal/preview").get_data(as_text=True)
    response = client.post("/seasonal/api/redesign", json={"season": "Christmas"})
    assert response.status_code == 400
    assert "error" in response.get_json()
    assert client.get("/seasonal/preview").get_data(as_text=True) == before


def test_preview_inlines_current_files(seasonal_app):
    files = seasonal.design_locally("Workers' Day")
    page = seasonal.assemble_preview(files)
    assert "./style.css" not in page
    assert "./script.js" not in page
    assert files["style.css"].strip() in page
    assert files["script.js"].strip() in page
    assert 'id="contact-form"' in page
