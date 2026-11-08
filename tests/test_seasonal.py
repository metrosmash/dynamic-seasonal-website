from __future__ import annotations

import io
import json
import shutil
import urllib.error

import pytest

from app import create_app
from app import seasonal
from app import wiki
from app.llm import ProviderError


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


def test_legacy_seasonal_path_redirects_home(client):
    response = client.get("/seasonal")
    assert response.status_code == 302
    assert response.location == "/"


def test_page_has_banner_toggles_reset_and_history_controls(client):
    response = client.get("/")
    assert response.status_code == 200
    page = response.get_data(as_text=True)
    assert "Proof of concept demo: seasonal redesigns are triggered by toggles here." in page
    for preset in ("Christmas", "Halloween", "Workers", "Children", "Eid al-Fitr (Sallah)"):
        assert preset in page
    assert "Enter your own season" in page
    assert "Imagine a website that redesigns itself for each season" in page
    normalized = " ".join(page.split())
    assert "automatically redesigns itself for that occasion" in normalized
    assert "Reset to original" in page
    assert 'id="back-button"' in page
    assert 'id="forward-button"' in page
    assert "/preview" in page
    assert 'href="/static/favicon.svg"' in page


def test_favicon_serves(client):
    response = client.get("/static/favicon.svg")
    assert response.status_code == 200
    assert response.content_type == "image/svg+xml; charset=utf-8"
    assert b"<svg" in response.data


def test_banner_stays_visible_after_redesign(client):
    assert client.post("/api/redesign", json={"season": "Halloween"}).status_code == 200
    page = client.get("/").get_data(as_text=True)
    assert "Proof of concept demo: seasonal redesigns are triggered by toggles here." in page


def test_redesign_replaces_current_season(client):
    assert client.post("/api/redesign", json={"season": "Christmas"}).status_code == 200
    preview = client.get("/preview").get_data(as_text=True)
    assert "Sample Caf" in preview and "Christmas" in preview

    body = client.post("/api/redesign", json={"season": "Halloween"}).get_json()
    assert body["season"] == "Halloween"
    preview = client.get("/preview").get_data(as_text=True)
    assert "Halloween" in preview
    assert "Christmas" not in preview


def test_custom_season_input(client):
    body = client.post(
        "/api/redesign", json={"season": "Cherry Blossom Festival"}
    ).get_json()
    assert body["season"] == "Cherry Blossom Festival"
    preview = client.get("/preview").get_data(as_text=True)
    assert "Cherry Blossom Festival" in preview


def test_empty_season_keeps_previous_version(client):
    before = client.get("/preview").get_data(as_text=True)
    response = client.post("/api/redesign", json={"season": "   "})
    assert response.status_code == 400
    assert "error" in response.get_json()
    assert client.get("/preview").get_data(as_text=True) == before


def test_history_steps_back_and_forward(client):
    client.post("/api/redesign", json={"season": "Christmas"})
    client.post("/api/redesign", json={"season": "Halloween"})
    state = client.get("/api/state").get_json()
    assert state["history"] == ["Original", "Christmas", "Halloween"]

    assert client.post("/api/back").get_json()["season"] == "Christmas"
    assert "Christmas" in client.get("/preview").get_data(as_text=True)
    assert client.post("/api/back").get_json()["season"] == "Original"
    assert client.post("/api/forward").get_json()["season"] == "Christmas"


def test_history_is_capped(client):
    for number in range(7):
        client.post("/api/redesign", json={"season": f"Season {number}"})
    state = client.get("/api/state").get_json()
    assert len(state["history"]) == seasonal.HISTORY_LIMIT
    assert state["season"] == "Season 6"


def test_reset_restores_original(client, seasonal_app):
    client.post("/api/redesign", json={"season": "Christmas"})
    body = client.post("/api/reset").get_json()
    assert body["season"] == "Original"
    assert body["history"] == ["Original"]
    site_files = seasonal.read_files(seasonal.site_dir(seasonal_app.config))
    original_files = seasonal.read_files(seasonal.original_dir(seasonal_app.config))
    assert site_files == original_files


def test_all_preset_designs_and_custom_design_pass_validation():
    for name in (*seasonal.get_presets(), "Cherry Blossom Festival", "Sallah", "Xmas!!!"):
        seasonal.validate_files(seasonal.design_locally(name))


def test_get_presets_comes_from_festivals_json_in_order():
    assert seasonal.get_presets() == [
        "Christmas",
        "Halloween",
        "Workers' Day",
        "Children's Day",
        "Eid al-Fitr (Sallah)",
    ]


def test_get_presets_respects_flag_and_skips_blank_labels(tmp_path, monkeypatch):
    path = tmp_path / "festivals.json"
    path.write_text(json.dumps([
        {"id": "a", "display_name": "  Alpha  ", "is_preset": True},
        {"id": "b", "display_name": "Beta", "is_preset": False},
        {"id": "c", "display_name": "Gamma"},
        {"id": "d", "display_name": "Delta", "is_preset": "would"},
        {"id": "e", "display_name": "Epsilon", "is_preset": "True"},
        {"id": "f", "display_name": "   ", "is_preset": True},
        {"id": "g", "is_preset": True},
        "not a dict",
    ]), encoding="utf-8")
    monkeypatch.setattr(seasonal, "FESTIVALS_PATH", path)
    assert seasonal.get_presets() == ["Alpha", "Epsilon"]


def test_missing_festivals_file_yields_no_presets_but_page_renders(
    client, monkeypatch, tmp_path
):
    monkeypatch.setattr(seasonal, "FESTIVALS_PATH", tmp_path / "absent.json")
    assert seasonal.get_presets() == []
    response = client.get("/")
    assert response.status_code == 200
    assert "Enter your own season" in response.get_data(as_text=True)


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
    monkeypatch.setattr(seasonal.llm, "complete_with_tools", complete)
    return app.test_client()


def test_llm_success_uses_returned_files(tmp_path, monkeypatch):
    seen = {}

    def fake_complete(messages, **kwargs):
        seen["messages"] = messages
        seen["tools"] = kwargs.get("tools", [])
        files = seasonal.design_locally("Christmas")
        files["index.html"] = files["index.html"].replace(
            "Sample Café at Christmas (sample text)", "LLM Marker Heading (sample text)"
        )
        return {"content": json.dumps(files)}

    client = _llm_client(tmp_path, monkeypatch, fake_complete)
    body = client.post("/api/redesign", json={"season": "Christmas"}).get_json()
    assert body["season"] == "Christmas"
    assert not body.get("warning")
    assert "LLM Marker Heading" in client.get("/preview").get_data(as_text=True)
    sent = " ".join(str(item.get("content", "")) for item in seen["messages"])
    assert "Redesign this website for the season: Christmas." in sent
    assert "Current site source files:" in sent
    assert any(
        tool.get("function", {}).get("name") == "festival_info" for tool in seen["tools"]
    )


def test_llm_unreachable_falls_back_to_builtin_with_warning(tmp_path, monkeypatch):
    def failing_complete(messages, **kwargs):
        raise ProviderError("AI provider could not be reached before the timeout.")

    client = _llm_client(tmp_path, monkeypatch, failing_complete)
    response = client.post("/api/redesign", json={"season": "Christmas"})
    assert response.status_code == 200
    body = response.get_json()
    assert "built-in designer" in body.get("warning", "")
    assert "Christmas" in client.get("/preview").get_data(as_text=True)


def test_llm_invalid_output_keeps_previous_version(tmp_path, monkeypatch):
    client = _llm_client(
        tmp_path, monkeypatch, lambda messages, **kwargs: {"content": "not json at all"}
    )
    before = client.get("/preview").get_data(as_text=True)
    response = client.post("/api/redesign", json={"season": "Christmas"})
    assert response.status_code == 400
    assert "error" in response.get_json()
    assert client.get("/preview").get_data(as_text=True) == before


def test_llm_tool_round_trip_grounds_design_in_verified_facts(tmp_path, monkeypatch):
    seen = {}
    files = seasonal.design_locally("Eid al-Fitr (Sallah)")
    calls = [
        {"content": "", "tool_calls": [{
            "id": "call_1",
            "type": "function",
            "function": {"name": "festival_info", "arguments": json.dumps({"name": "Sallah"})},
        }]},
        {"content": json.dumps(files)},
    ]

    def fake_complete(messages, **kwargs):
        seen.setdefault("rounds", []).append(list(messages))
        return calls.pop(0)

    client = _llm_client(tmp_path, monkeypatch, fake_complete)
    assert client.post("/api/redesign", json={"season": "Sallah"}).status_code == 200
    assert "Eid al-Fitr" in client.get("/preview").get_data(as_text=True)
    tool_messages = [
        item for item in seen["rounds"][1] if item.get("role") == "tool"
    ]
    assert tool_messages and "lantern" in tool_messages[0]["content"]
    assert '"found": true' in tool_messages[0]["content"]


def test_unknown_festival_tool_result_forbids_invention():
    assert seasonal.lookup_festival("Sallah")["id"] == "eid"
    assert seasonal.lookup_festival("Made Up Day") is None
    result = json.loads(seasonal.run_festival_tool("Made Up Day"))
    assert result["found"] is False
    assert "generic" in result["guidance"]


class _FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _stub_urlopen(monkeypatch, payloads):
    calls = {"count": 0}

    def fake_urlopen(request, timeout=None):
        payload = payloads[min(calls["count"], len(payloads) - 1)]
        calls["count"] += 1
        if isinstance(payload, Exception):
            raise payload
        return _FakeResponse(json.dumps(payload).encode("utf-8"))

    monkeypatch.setattr(wiki.urllib.request, "urlopen", fake_urlopen)
    return calls


def test_wiki_search_returns_summary(monkeypatch):
    _stub_urlopen(monkeypatch, [
        ["Diwali", ["Diwali"], [], []],
        {
            "type": "standard",
            "extract": "Diwali is a festival of lights celebrated by Hindus, Jains, Sikhs and some Buddhists.",
            "content_urls": {"desktop": {"page": "https://en.wikipedia.org/wiki/Diwali"}},
        },
    ])
    found = wiki.search_festival("Diwali")
    assert found["found"] is True
    assert found["title"] == "Diwali"
    assert "festival of lights" in found["summary"]


def test_wiki_search_skips_disambiguation_and_short_pages(monkeypatch):
    _stub_urlopen(monkeypatch, [
        ["X", ["X (disambiguation)", "X festival"], [], []],
        {"type": "disambiguation", "extract": "X may refer to many things here and there."},
        {"type": "standard", "extract": "X festival is a long-running harvest celebration held each autumn season with music."},
    ])
    found = wiki.search_festival("X")
    assert found["found"] is True
    assert found["title"] == "X festival"


def test_wiki_search_never_raises(monkeypatch):
    _stub_urlopen(monkeypatch, [["Nope", [], [], []]])
    assert wiki.search_festival("Nope") == {"found": False}
    _stub_urlopen(monkeypatch, [urllib.error.URLError("down")])
    assert wiki.search_festival("Diwali") == {"found": False}


def test_llm_falls_back_to_search_tool_for_unknown_festival(tmp_path, monkeypatch):
    monkeypatch.setattr(wiki, "search_festival", lambda name, timeout_s=8: {
        "found": True,
        "title": "Diwali",
        "summary": "Diwali is a festival of lights celebrated each autumn.",
        "url": "https://en.wikipedia.org/wiki/Diwali",
    })
    seen = {}
    files = seasonal.design_locally("Diwali")
    calls = [
        {"content": "", "tool_calls": [{
            "id": "call_1", "type": "function",
            "function": {"name": "festival_info", "arguments": json.dumps({"name": "Diwali"})},
        }]},
        {"content": "", "tool_calls": [{
            "id": "call_2", "type": "function",
            "function": {"name": "search_festival", "arguments": json.dumps({"name": "Diwali"})},
        }]},
        {"content": json.dumps(files)},
    ]

    def fake_complete(messages, **kwargs):
        seen.setdefault("rounds", []).append(list(messages))
        return calls.pop(0)

    client = _llm_client(tmp_path, monkeypatch, fake_complete)
    assert client.post("/api/redesign", json={"season": "Diwali"}).status_code == 200
    tool_contents = " ".join(
        item.get("content", "") for item in seen["rounds"][2] if item.get("role") == "tool"
    )
    assert '"found": false' in tool_contents  # curated lookup missed
    assert "festival of lights" in tool_contents  # search grounded it


def test_agent_stuck_on_tools_keeps_previous_version(tmp_path, monkeypatch):
    def looping_complete(messages, **kwargs):
        return {"content": "", "tool_calls": [{
            "id": "call_x",
            "type": "function",
            "function": {"name": "festival_info", "arguments": json.dumps({"name": "X"})},
        }]}

    client = _llm_client(tmp_path, monkeypatch, looping_complete)
    before = client.get("/preview").get_data(as_text=True)
    response = client.post("/api/redesign", json={"season": "Christmas"})
    assert response.status_code == 400
    assert client.get("/preview").get_data(as_text=True) == before


def test_preview_inlines_current_files(seasonal_app):
    files = seasonal.design_locally("Workers' Day")
    page = seasonal.assemble_preview(files)
    assert "./style.css" not in page
    assert "./script.js" not in page
    assert files["style.css"].strip() in page
    assert files["script.js"].strip() in page
    assert 'id="contact-form"' in page
