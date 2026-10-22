<p align="center">
  <b>linkedin-mcp</b><br>
  <i>A Model Context Protocol server for LinkedIn — with a quality gate that refuses posts which read as generated.</i>
</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue" alt="License"></a>
  <a href="https://github.com/AryanRajMaurya/linkedin-mcp"><img src="https://img.shields.io/badge/MCP-2.0-informational" alt="MCP"></a>
  <a href="https://github.com/AryanRajMaurya/linkedin-mcp"><img src="https://img.shields.io/badge/tests-passing-success" alt="Tests"></a>
</p>

---

## What it does

Point any MCP-capable agent at it and it can read a LinkedIn profile, check
a draft post and publish it, through the official LinkedIn API.

```json
{
  "mcpServers": {
    "linkedin": {
      "command": "linkedin-mcp",
      "env": {
        "LINKEDIN_ENGINE_HOME": "/home/you/.config/linkedin-engine"
      }
    }
  }
}
```

## The part that makes it different

A server that any agent can connect to, that publishes to a public feed on
request, is a footgun. Every automated posting tool has the same failure
mode: it produces something that technically publishes and reads as though
nobody wrote it.

So the **quality gate lives inside the server**. An agent cannot publish a
post that reads like a generated one, because the gate runs on the way out
and refuses it. The agent gets told what is wrong and fixes it.

| Rule | What it catches |
| --- | --- |
| `banned-phrase` | "thrilled to announce", "game-changer", "in today's fast-paced world", and thirty more |
| `weak-opening` | A first line that is a greeting rather than a claim |
| `emoji-run` | `🚀🚀🚀` — emoji used as punctuation |
| `emoji-count` | More than three emoji in a post |
| `exclamations` | Emphasis in punctuation |
| `no-link` | A post about something you built that does not let anyone reach it |
| `too-short` | Under 200 characters, which says nothing |
| `truncated` | Past the point where LinkedIn cuts it off mid-sentence |
| `filler` | "it's worth noting", "at the end of the day" |

Errors block the post. Warnings do not, but they are reported.

## The tools

| Tool | What it does |
| --- | --- |
| `linkedin_get_profile` | Reads the live profile: name, headline, about, location |
| `linkedin_update_profile` | Updates the headline, about or location, and diffs against the live one |
| `linkedin_check_post` | Runs the quality gate over a draft and returns what is wrong with it |
| `linkedin_publish_post` | Publishes — after the gate has passed |
| `linkedin_token_status` | Reports what the stored token is allowed to do |

Two resources, `linkedin://profile` and `linkedin://profile/written`, and a
prompt, `linkedin_draft_post`, that walks an agent through drafting a post
about a real artefact and checking it.

## Safety

Three rules, and they are not optional:

**The token is never a tool argument.** It is read from the credential store
that [`linkedin-engine`](https://github.com/AryanRajMaurya/linkedin-engine)
uses, and it never appears in a tool result, a log line or an error message.
An agent cannot ask this server for it — which means a prompt injection in a
web page cannot ask it for it either.

**Publishing is off by default.** Reads always work. Writes need
`LINKEDIN_ENGINE_ALLOW_PUBLISH=1` in the server's environment. A server
that publishes on request from any agent that connects to it is a bad idea
at best.

**A dry run needs no token.** `linkedin_publish_post` answers the only
question that matters — would this post go out — without needing the
application to be authorised first, so you can test the gate before the
LinkedIn app is even created.

## Setup

You need a LinkedIn application with the **Sign In With LinkedIn** product
(self-serve) and the **Share on LinkedIn** product (review, and the one
that grants `w_member_social`, without which you can read but not publish).

The setup, including the Company Page step that stops most people, is
documented in
[`linkedin-engine/docs/SETUP.md`](https://github.com/AryanRajMaurya/linkedin-engine/blob/main/docs/SETUP.md).

Authorise it once:

```bash
pip install linkedin-engine
linkedin-engine auth setup --client-id ... --client-secret ... --redirect-uri ...
linkedin-engine auth login
```

Then start the server:

```bash
linkedin-mcp            # stdio, for a local agent
linkedin-mcp --http     # streamable HTTP, for a shared server
```

## Configuration

| Variable | Default | What it does |
| --- | --- | --- |
| `LINKEDIN_ENGINE_ALLOW_PUBLISH` | off | Set to `1` to let the server write to LinkedIn |
| `LINKEDIN_ENGINE_HOME` | `~/.config/linkedin-engine` | Where the credentials live |
| `LINKEDIN_ENGINE_PROFILE` | `content/profile.json` | The written profile to diff against |
| `LINKEDIN_ENGINE_VISIBILITY` | `PUBLIC` | The default visibility for a post |

## See also

- [`linkedin-engine`](https://github.com/AryanRajMaurya/linkedin-engine) — the
  command line tool this server is built on. Same credential store, same
  quality gate, plus draft generation from your GitHub activity.
- [`shipfree`](https://github.com/AryanRajMaurya/shipfree) — the Agent Skill
  for deploying AI services on free tiers.

## Development

```bash
pip install -e ".[dev]"
pytest
ruff check . && ruff format --check .
mypy
```

## License

MIT — see [LICENSE](LICENSE).

Built by [Aryan Raj Maurya](https://github.com/AryanRajMaurya).
