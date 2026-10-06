# Handoff: Freelancer MCP server

For the next Claude Code session. Read this, then `DEPLOY_MCP.md`, then the bidding agent's own
`CLAUDE.md` (especially "Traps" and "The four bid submit paths") before changing anything.

## Goal

Expose the owner's Freelancer.com bidding agent as a remote MCP server, so it can be added to
claude.ai as a custom connector and used from web and mobile. Done when:

- all tools work from the MCP Inspector
- the server runs on the VPS over HTTPS with auth
- the owner can add it in claude.ai and search projects from the phone

The owner's original brief is `BRIEF.md` in this bundle.

## State

**Built and tested. Not yet deployed or run against the real Freelancer API.** The previous session
ran in a cloud sandbox with no SSH and no access to freelancer.com, so everything was tested against
the real agent code plus a fake Freelancer API.

- Code: branch `claude/vibrant-bell-ow54iy` of `github.com/dwopetweens/wave` (commits `ce7961c`,
  `52354cc` and the commit adding this file). The repo is **public**; it contains no agent code and no
  secrets, and must stay that way.
- Tests: 39 pass. 16 (OAuth flow, tools, fake backend) run anywhere; 23 (the adapter) need the agent
  code, via `AGENT_DIR`.
- Also verified in the sandbox: every tool through the MCP Inspector CLI with an OAuth token; the full
  OAuth flow and tool calls through Nginx 1.24 with TLS; the IP allowlist (403 off-range, sign-in
  pages open); streamed events passing through Nginx unbuffered.

## Files

All of these go in the root of the agent directory, next to `poller.py` and `portal.py`. All are
new; none replaces an agent file.

| Path | What it is |
| - | - |
| `mcp_server.py` | Entry point. `serve` (default), `init-auth`, `revoke-tokens`. Defines the 6 tools |
| `freelancer_mcp/agent_backend.py` | Adapter to the agent's modules. All Freelancer and DB logic |
| `freelancer_mcp/backend.py` | Backend interface, error types (`code` prefixes), `FakeBackend`, style checker |
| `freelancer_mcp/oauth.py` | Single-user OAuth provider (password + TOTP login page), SQLite token store |
| `freelancer_mcp/config.py` | `MCP_*` settings from env / `.env` |
| `freelancer_mcp/ratelimit.py` | Thread-safe limiter on Freelancer API calls, 429 back-off |
| `tests/test_mcp_server.py` | OAuth + tools over real HTTP (uvicorn), fake backend |
| `tests/test_agent_backend.py` | Adapter against the real agent code and a fake Freelancer API |
| `deploy/freelancer-mcp.service` | systemd unit (user `denniskiama-portal`, `.venv-mcp`) |
| `deploy/nginx-freelancer-mcp.conf` | Nginx site for `mcp.denniskiama.com` |
| `DEPLOY_MCP.md` | Step-by-step deployment, Inspector test, claude.ai setup |
| `mcp.env.example` | The `MCP_*` variables to append to the agent's `.env` |
| `requirements-mcp.txt`, `requirements-dev.txt` | Extra deps (`mcp>=2.3,<3`, `pyotp`, `python-dotenv`; dev adds `pytest`) |

## Tools

| Tool | Notes |
| - | - |
| `search_projects(query, min_budget, max_budget, skills, limit)` | Hides rows `approved`/`bid_submitted`. **Never writes to `projects.db`** |
| `get_project(project_id)` | Live project + client info scraped from the public page + `bid_rules` |
| `place_bid(project_id, amount, period_days, description)` | Write tool. Dry run unless `MCP_DRY_RUN=false` |
| `list_my_bids(status)` | `active` / `awarded` / `rejected` / `all`, from Freelancer's bid list |
| `get_messages(thread_id or project_id)` | Chronological, senders hydrated |
| `send_message(thread_id, text)` | Write tool. Dry run unless `MCP_DRY_RUN=false` |

Write tools are annotated `read_only_hint=False, idempotent_hint=False` so Claude asks first.
Errors reach Claude as `code: message` (`already_bid`, `agent_busy`, `invalid_input`, `not_found`,
`rate_limited`, `freelancer_auth`, `freelancer_error`).

## Decisions and why (don't undo without asking the owner)

1. **Separate Python 3.11 venv (`.venv-mcp`, via `uv`).** Production runs Python 3.9 and every MCP SDK
   release needs 3.10+. The agent's `.venv` is untouched. The new venv installs the agent's
   `requirements.txt` too, because the adapter imports `src/` and `portal.py`.
2. **No agent file is modified.** The adapter imports `load_config`, `FreelancerClient`, `Storage`,
   `pipeline.enforce_period_days` / `_enforce_floors`, `filters.is_dns` / `has_skill_overlap` /
   `filter_project`, and `portal._parse_fl_error`. `AgentFreelancerClient` subclasses the agent's
   client only to add `get_project(id)` and `get_projects(ids)`, using its `_get` and `_to_project`.
3. **`place_bid` is the agent's fifth submit path** and enforces the same rules as the other four
   (the agent's CLAUDE.md requires that): period at most 4 days, DNS exactly 1, the rate floors, at most
   the project's max budget, 100% milestone. **It refuses instead of clamping**, quoting the allowed
   value, because the owner approves exact numbers in chat.
4. **Double-bid protection:** refuse if the row is engaged; refuse `agent_busy` if the poller inserted
   the row at `new` within 15 minutes (it may be auto-bidding); check Freelancer's bidder list for the
   owner's user ID; then claim with one conditional `UPDATE ... SET status='approved' WHERE ... AND
   status NOT IN ('approved','bid_submitted')`. Any failure after the claim becomes `bid_failed` with
   the raw error, which the portal's history and Retry button parse. **No WAL**: switching the
   production DB's journal mode would affect the poller, portal and bot; the single-statement claim
   needs no more than SQLite's default write lock.
5. **Search and get_project never write to the DB.** `insert_new` before scoring is how the poller
   marks a project seen; an MCP write would hide projects from the poller (the agent's "dry run is
   destructive" trap).
6. **Auth: OAuth 2.1 through the MCP SDK's authorization-server support, single user.** claude.ai
   custom connectors support OAuth (DCR and CIMD) by default; static header auth is beta and limited
   to some organisations. Claude registers via DCR as a public client. Registration only accepts
   `https://claude.ai/api/mcp/auth_callback` and `https://claude.com/api/mcp/auth_callback` (loopback
   only with `MCP_ALLOW_LOOPBACK_REDIRECTS=true`). Login is password (scrypt) + TOTP with replay
   protection and a 15-minute lockout after 5 failures. Tokens are stored as SHA-256 hashes, bound to
   the MCP URL (RFC 8707), 1-hour access, rotating refresh with reuse detection.
7. **Nginx:** only `/authorize` and `/login` are open to the internet (the owner's browser needs them).
   Everything else accepts only Anthropic's egress range `160.79.104.0/21`. Buffering, caching and gzip
   are off. `listen 443 ssl http2;` rather than `http2 on;` because Ubuntu's Nginx 1.24 lacks the latter.
8. **Stateless Streamable HTTP** at `/mcp`, so restarts never strand Claude sessions.

## Facts checked in the previous session

- MCP Python SDK 2.x renamed `FastMCP` to `MCPServer` (`from mcp.server.mcpserver import MCPServer`)
  and uses `httpx2`, not `httpx`.
- The SDK checks the Host header for DNS rebinding. Nginx's `$host` drops the port, so the server
  accepts the public host with and without it.
- Single project: `GET /api/projects/0.1/projects/{id}/` returns the project as `result`. Batch:
  `GET /api/projects/0.1/projects/?projects[]=...` returns `result.projects`. Taken from Freelancer's
  official Python SDK; **not yet confirmed against the live API**.

## What's left, in order

1. **Run the tests locally.** Copy this bundle's files into a local copy of the agent directory, then
   in a Python 3.11+ venv from that directory:
   ```bash
   pip install -r requirements.txt -r requirements-dev.txt     # agent deps + MCP deps
   python -m pytest -q tests                                   # 16 pass, adapter tests skip
   AGENT_DIR=$PWD python -m pytest -q tests                    # 39 pass
   ```
2. **Server pre-flight**: `DEPLOY_MCP.md` step 0. Confirm the web server is Nginx (the portal is
   already at `https://portal.denniskiama.com`), that `DB_PATH` is inside the agent dir, and that the
   service user's home is `/home/denniskiama-portal`. If the web server is not Nginx, write the
   equivalent config, with the same open/allowlisted split and no buffering.
3. **Deploy**: `DEPLOY_MCP.md` steps 1 to 4 and 6 to 7. Follow the agent CLAUDE.md's file-copy
   conventions; the production host is in that file. Nothing of the agent needs restarting.
4. **Inspector on real data, dry run**: `DEPLOY_MCP.md` step 5. This is the first contact with the live
   API. Check especially:
   - `get_project` parses the live single-project response (`AgentFreelancerClient.get_project`)
   - `list_my_bids` titles and statuses: the batch call's shape, and the bid fields `award_status`,
     `complete_status`, `retracted`, `frontend_project_status` that `_bid_status()` reads
   - `get_messages` by `project_id`: thread `context` shape
   If a shape differs, fix `agent_backend.py` and update `FakeFreelancer` in
   `tests/test_agent_backend.py` to match the real response, so the tests keep describing reality.
5. **Connect in claude.ai** (`DEPLOY_MCP.md` step 8) and search from the phone.
6. **Go live only with the owner's explicit OK**: run a dry-run `place_bid` from Claude first, show the
   owner the result, and only set `MCP_DRY_RUN=false` when they say so. Never place a real bid or send
   a real message to test, unless the owner approves that specific one.

## Known limits and open items

- **Hire rate** is not available: neither the API (under this token) nor the public project page
  exposes it. `get_project` returns `hire_rate: null` with a note. Don't scrape harder without asking.
- **Search results lack client country and verification**: the search API returns them as null under
  this token (see the agent's CLAUDE.md), so the summary omits them; `get_project` has them.
- **Residual race with the auto-bidder.** If the poller is drafting an auto-bid (status
  `awaiting_approval`, roughly a minute) when the owner bids through Claude, Freelancer rejects the
  second bid, so no double bid happens, but the poller then overwrites the row to `bid_failed` and back
  to `awaiting_approval`. Proposed fix, **only with the owner's approval** because it touches the live
  auto-bid path: in `src/pipeline.py` `_attempt_auto_bid()`, claim the row right before
  `fl.submit_bid` with the same conditional `UPDATE` as `AgentBackend._claim`, and return `True`
  without submitting if the claim fails (returning `False` would fall through to
  `mark_awaiting_no_draft` and re-queue the project). Add the guard to the portal and bot paths too if
  the owner wants all five consistent.
- `mcp>=2.3,<3` is pinned below 3.0; SDK 3.0 changes `validate_token_resource` defaults (already set
  explicitly).

## Rules for the next session

- Don't modify the agent's existing files without asking the owner; if you do, follow its CLAUDE.md
  (all four, now five, submit paths stay consistent).
- Never run `poller.py --dry-run` against the production DB (it marks projects as seen).
- Never commit `.env`, `projects.db`, `mcp_auth.db`, `config.yaml` or agent code to the public repo.
- Keep `MCP_AUTH_DISABLED` for localhost-only testing; the server refuses it otherwise.

## Security to-dos for the owner

- The VPS root password was pasted into the previous chat. Change it, move to SSH keys, and set
  `PermitRootLogin prohibit-password` / `PasswordAuthentication no`.
- The agent CLAUDE.md says `portal.py` binds `0.0.0.0:8001`. If the firewall allows that port, the
  portal can be reached over plain HTTP by IP, skipping TLS. Check and bind it to `127.0.0.1` if Nginx
  proxies it.
