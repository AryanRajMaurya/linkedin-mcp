"""The LinkedIn MCP server.

Exposes LinkedIn's member API as tools, so any MCP-capable agent can read
the profile, check a draft and publish it.

The interesting part is not the API plumbing -- that is small. It is that
the **quality gate lives inside the server**. An agent cannot publish a post
that reads like a generated one, because the gate runs on the way out and
refuses it. That is the difference between a server that is a thin wrapper
over an HTTP API and one that is safe to point an agent at.

The tools are deliberately few, and they are written for an agent to read:
the docstrings become the tool descriptions, so they say what the tool is
for and when to reach for it.

Run it with:

    linkedin-mcp            # stdio, the usual transport for a local agent
    linkedin-mcp --http     # streamable HTTP, for a shared server
"""

from __future__ import annotations

from typing import Any

from linkedin_engine.auth import ensure_token
from linkedin_engine.client import LinkedInClient, LinkedInError
from linkedin_engine.config import Config, Token
from linkedin_engine.profile import Profile, load_profile, render_profile
from linkedin_engine.publish import publish as publish_draft
from linkedin_engine.quality import Level, check_post, summarise

from .config import profile_path, publishing_enabled, visibility_default

try:  # pragma: no cover - exercised by the import, not the logic
    from mcp.server.mcpserver import MCPServer
except ImportError as error:  # pragma: no cover
    raise SystemExit(
        "The MCP SDK is required. Install it with `pip install 'linkedin-mcp'` "
        "or `pip install mcp`."
    ) from error

__all__ = ["build_server", "main"]

INSTRUCTIONS = """\
Publish and maintain a LinkedIn profile through the official LinkedIn API.

Two rules make this safe to use:

1. **Always check a draft before publishing it.** `linkedin_check_post` runs
   the quality gate, which refuses the announcement formulas, emoji used as
   punctuation, a post with no link in it, and a first line that is a
   greeting rather than a claim. `linkedin_publish_post` runs the same gate
   and refuses to publish a draft that fails it. A post that goes out is
   visible to everyone and cannot be un-posted.

2. **Write about something that actually happened.** A post about a merged
   pull request, a shipped release or a published paper reads as work. A post
   about a plan reads as noise. If there is no artefact, do not post.
"""


def _client() -> LinkedInClient:
    """Build a client from the stored credentials."""
    config = Config.load()
    config.require()
    token = ensure_token(config)
    return LinkedInClient(token.access_token)


def _written_profile() -> Profile | None:
    """The written profile, if one can be found."""
    path = profile_path()
    if path is None:
        return None
    try:
        return load_profile(path)
    except RuntimeError:
        return None


def build_server() -> Any:
    """Build the MCP server with its tools, resources and prompts."""
    server = MCPServer(
        name="linkedin",
        instructions=INSTRUCTIONS,
    )

    # ------------------------------------------------------------------ tools

    @server.tool(
        name="linkedin_get_profile",
        title="Read the LinkedIn profile",
        description=(
            "Read the authenticated member's LinkedIn profile: name, headline, "
            "about and location. Use this before editing the profile, so you "
            "know what is live rather than guessing."
        ),
    )
    def linkedin_get_profile() -> dict[str, Any]:
        """Read the live profile."""
        try:
            live = _client().get_me(projection="(id,firstName,lastName,headline,about,location)")
        except (RuntimeError, LinkedInError) as error:
            return {"ok": False, "error": str(error)}

        return {"ok": True, "profile": live}

    @server.tool(
        name="linkedin_update_profile",
        title="Update the LinkedIn profile",
        description=(
            "Update the headline, the about section or the location on the "
            "profile. This is a dry run unless publishing has been enabled on "
            "the server, so it reports what would change before it changes "
            "anything. Returns the diff against the live profile."
        ),
    )
    def linkedin_update_profile(
        headline: str = "",
        about: str = "",
        location: str = "",
    ) -> dict[str, Any]:
        """Update the profile fields."""
        written = _written_profile()
        if written is None:
            return {
                "ok": False,
                "error": (
                    "No written profile was found, so there is nothing to apply. "
                    "Set LINKEDIN_ENGINE_PROFILE to the profile file, or place "
                    "the server in a checkout that has one at content/profile.json."
                ),
            }

        wanted = Profile(
            headline=headline or written.headline,
            about=about or written.about,
            location=location or written.location,
        )

        try:
            client = _client()
            live = client.get_me(projection="(id,firstName,lastName,headline,about,location)")
        except (RuntimeError, LinkedInError) as error:
            return {"ok": False, "error": str(error)}

        from linkedin_engine.profile import apply_profile, diff_profile

        differences = diff_profile(live, wanted)
        result = apply_profile(client, wanted, dry_run=not publishing_enabled())

        return {
            "ok": True,
            "sent": result["sent"],
            "differences": differences,
            "would_change": result["changed"],
            "note": (
                ""
                if result["sent"]
                else "Publishing is disabled on this server, so nothing was sent."
            ),
        }

    @server.tool(
        name="linkedin_check_post",
        title="Check a post before publishing it",
        description=(
            "Run the quality gate over a draft post and return what is wrong "
            "with it. Errors block publishing: the announcement formulas, emoji "
            "used as punctuation, a first line that is a greeting rather than "
            "a claim, a post with no link in it, and a length that says "
            "nothing. Warnings do not block. Use this before every post."
        ),
    )
    def linkedin_check_post(text: str) -> dict[str, Any]:
        """Check a draft against the quality gate."""
        findings = check_post(text)
        return {
            "ok": True,
            "publishable": not any(f.level is Level.ERROR for f in findings),
            "summary": summarise(findings),
            "findings": [
                {
                    "level": f.level.value,
                    "rule": f.rule,
                    "message": f.message,
                    "hint": f.hint,
                }
                for f in findings
            ],
        }

    @server.tool(
        name="linkedin_publish_post",
        title="Publish a post",
        description=(
            "Publish a text post to the member's feed. The quality gate runs "
            "first and refuses to publish a draft that fails it. This is a dry "
            "run unless publishing has been enabled on the server. Prefer "
            "linkedin_check_post first, so you can fix the problems it finds."
        ),
    )
    def linkedin_publish_post(
        text: str,
        visibility: str = "",
        dry_run: bool = True,
    ) -> dict[str, Any]:
        """Publish a draft."""
        chosen = (visibility or visibility_default()).upper()
        if chosen not in {"PUBLIC", "CONNECTIONS", "PRIVATE"}:
            return {"ok": False, "published": False, "error": f"unknown visibility {chosen!r}"}

        # The gate runs first, before the token is even looked at. A draft
        # that fails it is refused on its own merits, so the caller is told
        # what is wrong with the post rather than being sent off to fix
        # their authentication.
        findings = check_post(text)
        errors = [f for f in findings if f.level is Level.ERROR]
        if errors:
            return {
                "ok": False,
                "published": False,
                "reason": "; ".join(f.message for f in errors),
                "summary": summarise(findings),
                "findings": [
                    {"level": f.level.value, "rule": f.rule, "message": f.message} for f in findings
                ],
            }

        if not publishing_enabled():
            dry_run = True

        if dry_run:
            # A dry run needs no token. It answers the only question that
            # matters here -- would this post go out -- without needing the
            # application to be authorised first.
            return {
                "ok": True,
                "published": False,
                "post_id": "",
                "reason": ("dry run; publishing is disabled on this server, so nothing was sent"),
                "summary": summarise(findings),
                "findings": [
                    {
                        "level": f.level.value,
                        "rule": f.rule,
                        "message": f.message,
                    }
                    for f in findings
                ],
            }

        try:
            client = _client()
            result = publish_draft(
                client,
                text,
                dry_run=False,
                visibility=chosen,
            )
        except (RuntimeError, LinkedInError) as error:
            return {"ok": False, "published": False, "error": str(error)}

        return {
            "ok": result.published,
            "published": result.published,
            "post_id": result.post_id,
            "reason": result.reason,
            "summary": summarise(result.findings),
            "findings": [
                {
                    "level": f.level.value,
                    "rule": f.rule,
                    "message": f.message,
                }
                for f in result.findings
            ],
        }

    @server.tool(
        name="linkedin_token_status",
        title="Check what the LinkedIn token can do",
        description=(
            "Report what the stored LinkedIn token is allowed to do: whether it "
            "has expired, whether it can be refreshed, and which scopes were "
            "granted. Use this when publishing fails, to find out whether the "
            "application is missing the Share on LinkedIn product."
        ),
    )
    def linkedin_token_status() -> dict[str, Any]:
        """Report the token's state."""
        token = Token.load()
        if token is None:
            return {
                "ok": False,
                "error": (
                    "No token is stored. Authorise the application with "
                    "`linkedin-engine auth login` first."
                ),
            }

        return {
            "ok": True,
            "expired": token.expired,
            "has_refresh_token": bool(token.refresh_token),
            "scopes": token.scope or "unknown",
            "publishing_enabled": publishing_enabled(),
            "note": (
                "Publishing needs the w_member_social scope, which comes with "
                "the Share on LinkedIn product. Without it the token can still "
                "read the profile."
            ),
        }

    # -------------------------------------------------------------- resources

    @server.resource(
        "linkedin://profile",
        name="Live profile",
        description="The live LinkedIn profile of the authenticated member.",
    )
    def live_profile_resource() -> str:
        """The live profile, as JSON."""
        try:
            live = _client().get_me(projection="(id,firstName,lastName,headline,about,location)")
        except (RuntimeError, LinkedInError) as error:
            return f'{{"error": "{error}"}}'
        import json

        return json.dumps(live, indent=2)

    @server.resource(
        "linkedin://profile/written",
        name="Written profile",
        description=(
            "The written profile, as text, ready to paste into LinkedIn. The "
            "server keeps the profile in a versioned file so a change is a "
            "pull request rather than an edit in a form."
        ),
    )
    def written_profile_resource() -> str:
        """The written profile, as text."""
        written = _written_profile()
        if written is None:
            return "No written profile was found."
        return render_profile(written)

    # ---------------------------------------------------------------- prompts

    @server.prompt(
        name="linkedin_draft_post",
        description=(
            "Draft a LinkedIn post about something that actually happened, and "
            "run it through the quality gate."
        ),
    )
    def draft_post_prompt(artefact: str, detail: str = "") -> str:
        """A prompt for drafting a post about a real artefact."""
        return (
            "Write a LinkedIn post about the artefact below.\n\n"
            "Artefact:\n"
            f"{artefact}\n\n" + (f"Detail:\n{detail}\n\n" if detail else "") + "Rules:\n"
            "- Say what happened and what was interesting about it. Not how you "
            "feel about building it.\n"
            "- The first line is the only line most people will read. Open with "
            "the claim or the number, not a greeting.\n"
            "- No announcement formulas: 'thrilled to announce', 'game-changer', "
            "'in today's fast-paced world', and so on.\n"
            "- One emoji at most, and never two in a row.\n"
            "- Link the artefact. A post about something you built should let "
            "people reach it.\n"
            "- Between 400 and 1,800 characters.\n\n"
            "Then call linkedin_check_post on your draft, and fix anything it "
            "reports before publishing."
        )

    return server


def main() -> int:
    """Run the server."""
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--http",
        action="store_true",
        help="serve over streamable HTTP instead of stdio",
    )
    parser.add_argument(
        "--host", default="127.0.0.1", help="the host to bind when serving over HTTP"
    )
    parser.add_argument(
        "--port", type=int, default=8765, help="the port to bind when serving over HTTP"
    )
    args = parser.parse_args()

    server = build_server()

    if args.http:
        server.run(transport="streamable-http", host=args.host, port=args.port)
    else:
        server.run(transport="stdio")

    return 0
