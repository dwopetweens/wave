# Deploying the Freelancer MCP server

This adds a remote MCP server to the bidding agent, so you can add it to Claude as a custom
connector and search, research, bid and reply from web and mobile.

| | |
| - | - |
| Connector URL | `https://mcp.denniskiama.com/mcp` |
| Agent directory | `/home/denniskiama-portal/freelancer-bidder` |
| Runs as | `denniskiama-portal` (same user as the poller, portal and bot) |
| Python | 3.11 in its own `.venv-mcp` (the MCP SDK needs 3.10+; the agent's `.venv` stays on 3.9) |

## What changes on the server

Only new files are added: `mcp_server.py`, `freelancer_mcp/`, `requirements-mcp.txt`, `deploy/`,
`.venv-mcp/`, and at runtime `mcp_auth.db`. No existing file is modified, so the poller, portal and
Telegram bot keep running exactly as they do now, and nothing needs restarting.

The server imports the agent's own modules (`src/config.py`, `src/freelancer_client.py`,
`src/storage.py`, the period and amount clamps in `src/pipeline.py`, the error parser in `portal.py`)
and shares `projects.db`:

- `search_projects` hides projects whose row is `approved` or `bid_submitted`, and never writes to the
  database, so the poller still scores everything it finds
- `place_bid` is a fifth submit path and applies the same rules as the other four: at most 4 days
  (DNS: 1 day), the rate floors, the project's max budget, a 100% milestone. If a number breaks a rule it
  refuses and says what is allowed instead of changing it, since you approved the exact bid in chat
- before submitting it checks Freelancer's bid list for your user ID, then claims the row with one
  conditional `UPDATE` (status to `approved` unless it already is), so whichever path gets there first
  wins and the others stop. It also refuses a project the poller inserted in the last 15 minutes and is
  still scoring (`agent_busy`)
- a successful bid is logged exactly like a portal bid (`bid_submitted`, `submitted_bid_id`, the
  proposal and numbers); a failed one becomes `bid_failed` with the raw error, so the portal's history
  and Retry button work on it

## How it fits together

```
Claude (web / desktop / phone)
   │  HTTPS, from Anthropic's IP range 160.79.104.0/21
   ▼
Nginx  ── TLS (Let's Encrypt), streaming unbuffered, IP allowlist
   │  http://127.0.0.1:8765
   ▼
mcp_server.py (systemd: freelancer-mcp)  ── OAuth sign-in, rate limit, dry-run switch
   │  imports src/ and portal.py
   ▼
Freelancer API (same token as the agent)  +  projects.db (shared with poller, portal, bot)
```

Sign-in is OAuth 2.1 for one user. When you connect, Claude opens a page on `mcp.denniskiama.com`
asking for a password and a 6-digit code from an authenticator app. Claude then gets 1-hour access
tokens and rotating refresh tokens. Only the two sign-in pages are reachable from the whole internet;
the MCP endpoint and the token endpoints only accept Anthropic's servers.

## 0. Check the server first

```bash
python3 --version                                     # the agent's interpreter (3.9 expected)
ss -ltnp | grep -E ':(80|443) '                       # which web server serves portal.denniskiama.com
D=/home/denniskiama-portal/freelancer-bidder
ls $D/mcp_server.py $D/freelancer_mcp 2>/dev/null     # should print nothing
grep '^DB_PATH' $D/.env                               # empty or projects.db: the database is in $D
```

If `DB_PATH` points outside the agent directory, add that directory to `ReadWritePaths=` in
`deploy/freelancer-mcp.service`; systemd only lets the server write inside the paths listed there.

The steps below assume Nginx (the `ss` line shows `nginx`). If it shows something else (Caddy,
Apache, a Cloudflare tunnel), stop at step 6 and ask for the matching config.

## 1. DNS

Add an `A` record for `mcp.denniskiama.com` with the same IP as `portal.denniskiama.com`, then check:

```bash
dig +short mcp.denniskiama.com
```

## 2. Copy the files

On your laptop:

```bash
git clone -b claude/vibrant-bell-ow54iy https://github.com/dwopetweens/wave.git freelancer-mcp
cd freelancer-mcp
tar czf mcp.tgz mcp_server.py freelancer_mcp requirements-mcp.txt deploy mcp.env.example
scp mcp.tgz root@YOUR_SERVER:/tmp/
```

On the server (as root). Every file is new, so nothing of the agent is overwritten:

```bash
D=/home/denniskiama-portal/freelancer-bidder
tar xzf /tmp/mcp.tgz -C $D
chown -R denniskiama-portal:denniskiama-portal $D/mcp_server.py $D/freelancer_mcp $D/requirements-mcp.txt $D/deploy $D/mcp.env.example
```

## 3. Python 3.11 venv

```bash
su - denniskiama-portal -c 'curl -LsSf https://astral.sh/uv/install.sh | sh'
su - denniskiama-portal -c 'cd ~/freelancer-bidder &&
  ~/.local/bin/uv venv --python 3.11 .venv-mcp &&
  ~/.local/bin/uv pip install --python .venv-mcp/bin/python -r requirements.txt -r requirements-mcp.txt'
su - denniskiama-portal -c 'cd ~/freelancer-bidder &&
  .venv-mcp/bin/python -c "import mcp, src.config, portal, freelancer_mcp.agent_backend; print(\"imports ok\")"'
```

`uv` downloads its own Python 3.11 into the user's home; the system Python and `.venv` are untouched.

## 4. Configure

Create your login. It asks for a password (12+ characters) and prints two lines:

```bash
su - denniskiama-portal -c 'cd ~/freelancer-bidder && .venv-mcp/bin/python mcp_server.py init-auth'
```

Add the setup key it prints to your authenticator app (Google Authenticator, 1Password, Aegis...).
Then append to the agent's `.env`, pasting the two printed lines where shown:

```bash
cat >> /home/denniskiama-portal/freelancer-bidder/.env <<'EOF'

# --- MCP server ---
MCP_PUBLIC_URL=https://mcp.denniskiama.com
MCP_HOST=127.0.0.1
MCP_PORT=8765
MCP_BACKEND=agent
MCP_DRY_RUN=true
MCP_MAX_BID_AMOUNT=1500
MCP_OWNER_PASSWORD_HASH=paste-from-init-auth
MCP_OWNER_TOTP_SECRET=paste-from-init-auth
EOF
chmod 600 /home/denniskiama-portal/freelancer-bidder/.env
```

The poller, portal and bot ignore these variables. `MCP_MAX_BID_AMOUNT` is a ceiling on any single MCP
bid, in the project's currency; adjust or remove it.

## 5. Test with the MCP Inspector on real data (dry run)

Before exposing anything, run a temporary private instance with sign-in off. It refuses to start
without auth unless both its address and its public URL are localhost.

On the server:

```bash
su - denniskiama-portal -c 'cd ~/freelancer-bidder && env MCP_AUTH_DISABLED=true MCP_DRY_RUN=true \
  MCP_PORT=8766 MCP_PUBLIC_URL=http://127.0.0.1:8766 .venv-mcp/bin/python mcp_server.py'
```

On your laptop, in two terminals:

```bash
ssh -N -L 8766:127.0.0.1:8766 root@YOUR_SERVER
npx @modelcontextprotocol/inspector
```

In the Inspector choose **Streamable HTTP**, URL `http://localhost:8766/mcp`, **Connect**, and run:

- `search_projects` with `skills: ["wordpress"]`: real projects, none you have bid on; each shows
  whether the agent has seen it (`agent.status`, `agent.score`)
- `get_project` on one of them: client country, rating, reviews, payment verified, bid count, and
  `bid_rules` (amount range, period)
- `list_my_bids` with `active`, `awarded`, `rejected`
- `get_messages` with a `project_id` you have a conversation on
- `place_bid` on a real project: returns `"dry_run": true` and the exact bid it would send, plus
  `style_warnings`; nothing is sent and `projects.db` is not touched
- `place_bid` with `period_days: 6`: refused with the allowed value
- `place_bid` on a project the agent already bid on: `already_bid`
- `send_message`: dry run, nothing sent

Stop it with Ctrl-C.

## 6. systemd service

```bash
cp /home/denniskiama-portal/freelancer-bidder/deploy/freelancer-mcp.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now freelancer-mcp
systemctl status freelancer-mcp
curl -s http://127.0.0.1:8765/healthz        # {"ok": true, "backend": "agent", "dry_run": true}
journalctl -u freelancer-mcp -f              # logs
```

## 7. Nginx and Let's Encrypt

```bash
apt install certbot python3-certbot-nginx     # skip if the portal's certificate already uses certbot
certbot certonly --nginx -d mcp.denniskiama.com

cp /home/denniskiama-portal/freelancer-bidder/deploy/nginx-freelancer-mcp.conf /etc/nginx/sites-available/freelancer-mcp
ln -s /etc/nginx/sites-available/freelancer-mcp /etc/nginx/sites-enabled/
nginx -t && systemctl reload nginx
```

If `nginx -t` complains that `/etc/letsencrypt/options-ssl-nginx.conf` or `ssl-dhparams.pem` is
missing, delete those two lines from the site file; they only tune TLS settings.

Reload Nginx after each certificate renewal:

```bash
printf '#!/bin/sh\nsystemctl reload nginx\n' > /etc/letsencrypt/renewal-hooks/deploy/reload-nginx
chmod +x /etc/letsencrypt/renewal-hooks/deploy/reload-nginx
certbot renew --dry-run
```

What the site config does:

- buffering, caching and gzip off with a 1-hour read timeout, so streamed MCP responses reach Claude as
  they are produced
- `/mcp`, `/token`, `/register` and `/.well-known/*` only accept `160.79.104.0/21`, Anthropic's published
  egress range ([current list](https://platform.claude.com/docs/en/api/ip-addresses)); update the `allow`
  line if Anthropic changes it
- `/authorize` and `/login` are open because your own browser opens them; `/login` is rate-limited
  (10 per minute per IP), and the server locks sign-in for 15 minutes after 5 failures

Check from your laptop:

```bash
curl -si https://mcp.denniskiama.com/mcp | head -1          # 403: not from Anthropic, as intended
curl -si https://mcp.denniskiama.com/authorize | head -1    # 400: reaches the server, TLS works
```

## 8. Add it to Claude

1. Open **claude.ai > Settings > Connectors > Add custom connector**.
2. Name `Freelancer`, remote MCP server URL:

   ```
   https://mcp.denniskiama.com/mcp
   ```

3. Leave the OAuth client settings at their defaults; Claude registers itself.
4. **Add**, then **Connect**. A page on `mcp.denniskiama.com` asks "Allow access to your Freelancer.com
   account?" Enter your password and authenticator code, then **Allow**. Only do this right after
   clicking Connect yourself; never on a link someone sends you.
5. On your phone, the connector is in the Claude app under the same account. Enable it in a chat and
   try: "Search Freelancer for WordPress migration projects over $100."

`place_bid` and `send_message` are marked as write tools (not read-only, not idempotent), so Claude
asks before running them. Keep them on asking first if you change the connector's tool permissions.

## 9. Go live

Once a dry-run `place_bid` from Claude on your phone shows the bid you expect:

```bash
sed -i 's/^MCP_DRY_RUN=true/MCP_DRY_RUN=false/' /home/denniskiama-portal/freelancer-bidder/.env
systemctl restart freelancer-mcp
```

Bids placed through Claude are manual bids to the portal (`auto_submitted = 0`), so its history screen
shows them once Freelancer marks them won or lost, like bids submitted from the portal.

## Operations

| Task | Command |
| - | - |
| Logs | `journalctl -u freelancer-mcp -f` |
| Sign every Claude client out | `su - denniskiama-portal -c 'cd ~/freelancer-bidder && .venv-mcp/bin/python mcp_server.py revoke-tokens'` |
| Change password or authenticator | run `init-auth` again, update `.env`, `systemctl restart freelancer-mcp` |
| Back to dry run | set `MCP_DRY_RUN=true` in `.env`, `systemctl restart freelancer-mcp` |
| Stop it entirely | `systemctl disable --now freelancer-mcp` |

To update the server's code, copy new files the way the agent's CLAUDE.md describes (stage to a
dotfile, back up to `.backups/`, `mv` into place), then `systemctl restart freelancer-mcp`. Unlike
`portal.py`, it is managed by systemd, so a restart is all it needs.

If you suspect the password or authenticator secret leaked, change both and run `revoke-tokens`.

## Optional: the Inspector against the public server, with OAuth

To test the real sign-in from the Inspector, add `allow YOUR.LAPTOP.IP;` in `location /` of the Nginx
site, set `MCP_ALLOW_LOOPBACK_REDIRECTS=true` in `.env`, reload Nginx and restart the service, then
connect the Inspector to `https://mcp.denniskiama.com/mcp` and follow its sign-in. Undo both afterwards.
