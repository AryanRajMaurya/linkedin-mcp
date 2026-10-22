"""Tests for the LinkedIn MCP server.

The server is the thing an agent talks to, so the things that matter are
that the tools answer, that the quality gate is actually enforced on the
way out, and that the server cannot be talked into publishing by accident.
"""

from __future__ import annotations

import asyncio
import json

from linkedin_mcp.config import (
    PROFILE_ENV,
    PUBLISH_FLAG,
    profile_path,
    publishing_enabled,
    visibility_default,
)
from linkedin_mcp.server import build_server

A_GOOD_POST = """\
Merged a pull request that pipes the upstream response instead of buffering it.

The response is piped rather than parsed, and that is the whole trick. Time
spent waiting on a socket is not CPU time, so the request costs almost
nothing. Buffering a multi-megabyte response parses it, and parsing is the
expensive part.

The part that bit was the D1 query limit: fifty queries per invocation, which
a loop over twenty conversations blows through before it does anything else.

Details: https://github.com/example/project/pull/12
"""

A_BAD_POST = (
    "Hello everyone! I am thrilled to announce 🚀🚀🚀 that I have been working "
    "on something amazing for a while now and it is finally here!!\n\n"
    "https://example.com/thing"
)


def call(name: str, arguments: dict | None = None):
    """Call a tool on a fresh server."""
    server = build_server()
    result = asyncio.run(server.call_tool(name, arguments or {}))
    return result


def payload(result) -> dict:
    """Pull the JSON payload out of a tool result."""
    text = "".join(block.text for block in result.content if getattr(block, "text", None))
    return json.loads(text)


# ------------------------------------------------------------------- config


def test_publishing_is_off_by_default(monkeypatch) -> None:
    monkeypatch.delenv(PUBLISH_FLAG, raising=False)
    assert publishing_enabled() is False


def test_publishing_can_be_turned_on(monkeypatch) -> None:
    for value in ("1", "true", "YES", "on"):
        monkeypatch.setenv(PUBLISH_FLAG, value)
        assert publishing_enabled() is True


def test_the_visibility_defaults_to_public(monkeypatch) -> None:
    monkeypatch.delenv("LINKEDIN_ENGINE_VISIBILITY", raising=False)
    assert visibility_default() == "PUBLIC"


def test_an_unknown_visibility_falls_back_to_public(monkeypatch) -> None:
    monkeypatch.setenv("LINKEDIN_ENGINE_VISIBILITY", "sideways")
    assert visibility_default() == "PUBLIC"


def test_the_profile_path_follows_the_environment(monkeypatch, tmp_path) -> None:
    profile = tmp_path / "profile.json"
    profile.write_text("{}")
    monkeypatch.setenv(PROFILE_ENV, str(profile))
    assert profile_path() == profile


def test_a_missing_profile_is_not_an_error(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv(PROFILE_ENV, str(tmp_path / "nope.json"))
    assert profile_path() is None


# --------------------------------------------------------------------- tools


def test_the_server_exposes_the_expected_tools() -> None:
    server = build_server()
    names = {tool.name for tool in asyncio.run(server.list_tools())}
    assert names == {
        "linkedin_get_profile",
        "linkedin_update_profile",
        "linkedin_check_post",
        "linkedin_publish_post",
        "linkedin_token_status",
    }


def test_checking_a_good_post_says_it_is_publishable() -> None:
    result = payload(call("linkedin_check_post", {"text": A_GOOD_POST}))
    assert result["ok"] is True
    assert result["publishable"] is True
    assert not [f for f in result["findings"] if f["level"] == "error"]


def test_checking_a_bad_post_reports_the_problems() -> None:
    result = payload(call("linkedin_check_post", {"text": A_BAD_POST}))
    assert result["publishable"] is False
    rules = {f["rule"] for f in result["findings"]}
    assert "banned-phrase" in rules
    assert "weak-opening" in rules
    assert "emoji-run" in rules


def test_a_bad_post_is_never_published(monkeypatch) -> None:
    """The gate is enforced on the way out, not just on request."""
    monkeypatch.setenv(PUBLISH_FLAG, "1")
    result = payload(call("linkedin_publish_post", {"text": A_BAD_POST, "dry_run": False}))
    assert result["published"] is False
    assert result["ok"] is False
    # The gate refuses it on its own merits, not because of a missing token.
    assert "banned" in result["reason"] or "announcement" in result["reason"]


def test_publishing_is_a_dry_run_when_it_is_not_enabled(monkeypatch, tmp_path) -> None:
    """A dry run needs no token: it answers whether the post would go out."""
    monkeypatch.delenv(PUBLISH_FLAG, raising=False)
    monkeypatch.setenv("LINKEDIN_ENGINE_HOME", str(tmp_path))
    result = payload(call("linkedin_publish_post", {"text": A_GOOD_POST, "dry_run": False}))
    assert result["published"] is False
    assert result["ok"] is True
    assert "dry run" in result["reason"]


def test_an_unknown_visibility_is_refused() -> None:
    result = payload(call("linkedin_publish_post", {"text": A_GOOD_POST, "visibility": "sideways"}))
    assert result["ok"] is False
    assert "visibility" in result["error"]


def test_the_token_status_explains_a_missing_token(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("LINKEDIN_ENGINE_HOME", str(tmp_path))
    result = payload(call("linkedin_token_status"))
    assert result["ok"] is False
    assert "auth login" in result["error"]


def test_reading_the_profile_without_a_token_fails_cleanly(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("LINKEDIN_ENGINE_HOME", str(tmp_path))
    result = payload(call("linkedin_get_profile"))
    assert result["ok"] is False
    assert result["error"]


def test_no_tool_ever_returns_the_token(monkeypatch, tmp_path) -> None:
    """The token is not a tool argument, so it cannot be asked for."""
    monkeypatch.setenv("LINKEDIN_ENGINE_HOME", str(tmp_path))
    for name in (
        "linkedin_get_profile",
        "linkedin_update_profile",
        "linkedin_check_post",
        "linkedin_publish_post",
        "linkedin_token_status",
    ):
        text = json.dumps(payload(call(name, {"text": A_GOOD_POST})))
        assert "access_token" not in text
        assert "oauth_token" not in text


def test_updating_the_profile_needs_a_written_profile(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("LINKEDIN_ENGINE_HOME", str(tmp_path))
    monkeypatch.setenv(PROFILE_ENV, str(tmp_path / "missing.json"))
    result = payload(call("linkedin_update_profile", {"headline": "New"}))
    assert result["ok"] is False
    assert "profile" in result["error"].lower()


# ----------------------------------------------------------------- resources


def test_the_written_profile_resource_renders() -> None:
    server = build_server()
    contents = asyncio.run(server.read_resource("linkedin://profile/written"))
    text = "".join(getattr(block, "content", "") for block in contents)
    assert "Headline" in text or "written profile" in text
