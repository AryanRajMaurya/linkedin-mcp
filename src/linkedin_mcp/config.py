"""Configuration for the LinkedIn MCP server.

Two things matter here, and both are about not letting an agent do damage
by accident.

**The token is never a tool argument.** It is read from the credential
store that ``linkedin-engine`` uses and it never appears in a tool result,
a log line or an error message. An agent cannot ask this server for it,
which means a prompt injection in a web page cannot ask it for it either.

**Publishing is off unless it is explicitly turned on.** A server that any
agent can connect to and that publishes to a public feed on request is a
footgun. Reads are always available; writes need
``LINKEDIN_ENGINE_ALLOW_PUBLISH=1`` in the environment.
"""

from __future__ import annotations

import os
from pathlib import Path

__all__ = [
    "publishing_enabled",
    "profile_path",
    "visibility_default",
    "repo_root",
]

#: The environment variable that turns publishing on.
PUBLISH_FLAG = "LINKEDIN_ENGINE_ALLOW_PUBLISH"

#: Where the written profile lives.
PROFILE_ENV = "LINKEDIN_ENGINE_PROFILE"

#: The default visibility for a post.
VISIBILITY_ENV = "LINKEDIN_ENGINE_VISIBILITY"

#: Candidate locations for the written profile, in order.
PROFILE_CANDIDATES = (
    Path("content/profile.json"),
    Path("../linkedin-engine/content/profile.json"),
    Path("../../linkedin-engine/content/profile.json"),
)


def publishing_enabled() -> bool:
    """Whether the server is allowed to write to LinkedIn.

    Defaults to off. The value is read fresh on every call rather than at
    import time, so the server can be started read-only and switched on
    later without a restart in the common case.
    """
    value = os.environ.get(PUBLISH_FLAG, "").strip().lower()
    return value in {"1", "true", "yes", "on"}


def visibility_default() -> str:
    """The default visibility for a post."""
    value = os.environ.get(VISIBILITY_ENV, "PUBLIC").strip().upper()
    return value if value in {"PUBLIC", "CONNECTIONS", "PRIVATE"} else "PUBLIC"


def repo_root() -> Path:
    """The directory the server was started in."""
    return Path.cwd()


def profile_path() -> Path | None:
    """Find the written profile, if there is one.

    The profile is optional. Without it the server can still read and post,
    it just cannot diff the live profile against a written one.
    """
    explicit = os.environ.get(PROFILE_ENV, "").strip()
    if explicit:
        candidate = Path(explicit).expanduser()
        return candidate if candidate.exists() else None

    for candidate in PROFILE_CANDIDATES:
        if candidate.exists():
            return candidate

    return None
