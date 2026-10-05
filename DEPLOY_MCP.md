# Deploying the Freelancer MCP server

This puts the bidding agent behind a remote MCP server at `https://mcp.example.com/mcp`, so
you can add it to Claude as a custom connector and search, research and bid from web and mobile.

Replace these placeholders everywhere below:

| Placeholder | Meaning | Example |
| - | - | - |
| `mcp.example.com` | The subdomain for the MCP server | `mcp.yourdomain.com` |
| `AGENT_DIR` | The directory the agent runs from | `/opt/freelancer-agent` |
| `AGENT_USER` | The Linux user the agent runs as | `freelancer` |

## How it fits together

```
Claude (web / desktop / phone)
   │  HTTPS, from Anthropic's IP range 160.79.104.0/21
   ▼
Nginx on the VPS  ── TLS (Let's Encrypt), no buffering, IP allowlist
   │  http://127.0.0.1:8765
   ▼
mcp_server.py (systemd: freelancer-mcp)  ── OAuth sign-in, rate limit, dry-run switch
   │  imports the agent's own modules
   ▼
Freelancer API client + the agent's SQLite database (shared with the auto-agent)
```

Sign-in is OAuth 2.1, run by the server itself, for one user (you). When you connect, Claude opens
a page on `mcp.example.com` where you enter a password plus a 6-digit code from an authenticator
app. Claude then gets 1-hour access tokens and rotating refresh tokens. Only `/authorize` and
`/login` are reachable from the internet at large (your browser needs them); the MCP endpoint
and the token endpoints only accept Anthropic's servers.

## 1. DNS

Create an `A` record (and `AAAA` if the VPS has IPv6) for `mcp.example.com` pointing at the VPS.
Check it resolves before getting a certificate:

```bash
dig +short mcp.example.com
```

## 2. Install the server next to the agent

```bash
cd AGENT_DIR
sudo -u AGENT_USER git fetch origin claude/vibrant-bell-ow54iy
sudo -u AGENT_USER git checkout claude/vibrant-bell-ow54iy
sudo -u AGENT_USER AGENT_DIR/venv/bin/pip install -r requirements-mcp.txt
```

## 3. Configure

Generate your login (it asks for a password, then prints two lines):

```bash
sudo -u AGENT_USER AGENT_DIR/venv/bin/python mcp_server.py init-auth
```

Add the setup key it prints to your authenticator app (Google Authenticator, 1Password, Aegis...).
Then append to `AGENT_DIR/.env`, using `.env.example` as the reference:

```bash
MCP_PUBLIC_URL=https://mcp.example.com
MCP_HOST=127.0.0.1
MCP_PORT=8765
MCP_BACKEND=agent
MCP_DRY_RUN=true
MCP_MAX_BID_AMOUNT=1500
MCP_OWNER_PASSWORD_HASH=scrypt:...        # from init-auth
MCP_OWNER_TOTP_SECRET=...                 # from init-auth
```

Keep `.env` private: `chmod 600 AGENT_DIR/.env`. It is in `.gitignore`; never commit it.

## 4. Test with the MCP Inspector on real data (dry run)

Before exposing anything, run a private, temporary instance on the VPS with sign-in off. It only
listens on localhost, and the server refuses to start without auth on any other address.

On the VPS:

```bash
cd AGENT_DIR
sudo -u AGENT_USER env MCP_AUTH_DISABLED=true MCP_DRY_RUN=true \
  MCP_PORT=8766 MCP_PUBLIC_URL=http://127.0.0.1:8766 \
  AGENT_DIR/venv/bin/python mcp_server.py
```

On your laptop, tunnel to it and open the Inspector:

```bash
ssh -N -L 8766:127.0.0.1:8766 you@your-vps
npx @modelcontextprotocol/inspector
```

In the Inspector, choose transport **Streamable HTTP**, URL `http://localhost:8766/mcp`, then
**Connect**. Run each tool:

- `search_projects` with a query you would really search for
- `get_project` on one of the results: check the client country, rating, payment verified, hire rate and bid count
- `list_my_bids` with `active`, `awarded`, `rejected`
- `get_messages` with a `thread_id` or `project_id` from a real conversation
- `place_bid` and `send_message`: with `MCP_DRY_RUN=true` they return `"dry_run": true` and
  what would have been sent; nothing reaches Freelancer.com or the database
- `place_bid` on a project the agent already bid on: must return `already_bid`

Stop it with Ctrl-C when done.

## 5. systemd service

```bash
sudo cp AGENT_DIR/deploy/freelancer-mcp.service /etc/systemd/system/
sudo sed -i 's#AGENT_DIR#/opt/freelancer-agent#g; s#AGENT_USER#freelancer#g' /etc/systemd/system/freelancer-mcp.service
sudo systemctl daemon-reload
sudo systemctl enable --now freelancer-mcp
systemctl status freelancer-mcp
curl -s http://127.0.0.1:8765/healthz      # {"ok": true, "backend": "agent", "dry_run": true}
journalctl -u freelancer-mcp -f            # logs
```

## 6. Nginx and Let's Encrypt

```bash
sudo apt install nginx certbot python3-certbot-nginx
sudo ufw allow 'Nginx Full'                 # if ufw is on

# Get the certificate first (the site config refers to its files)
sudo certbot certonly --nginx -d mcp.example.com

sudo cp AGENT_DIR/deploy/nginx-freelancer-mcp.conf /etc/nginx/sites-available/freelancer-mcp
sudo sed -i 's/mcp.example.com/mcp.yourdomain.com/g' /etc/nginx/sites-available/freelancer-mcp
sudo ln -s /etc/nginx/sites-available/freelancer-mcp /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

Certbot's timer renews the certificate. To reload Nginx after each renewal:

```bash
printf '#!/bin/sh\nsystemctl reload nginx\n' | sudo tee /etc/letsencrypt/renewal-hooks/deploy/reload-nginx
sudo chmod +x /etc/letsencrypt/renewal-hooks/deploy/reload-nginx
sudo certbot renew --dry-run
```

What the config does:

- `proxy_buffering off`, `proxy_request_buffering off`, `proxy_cache off`, `gzip off` and a 1-hour
  read timeout, so streamed MCP responses reach Claude as they are produced
- `/mcp`, `/token`, `/register` and `/.well-known/*` only accept `160.79.104.0/21`, Anthropic's
  published egress range. If Anthropic changes it, update the `allow` line
  ([current list](https://platform.claude.com/docs/en/api/ip-addresses))
- `/authorize` and `/login` are open, since your browser opens them; `/login` is rate-limited
  (10 per minute per IP), and the server locks sign-in for 15 minutes after 5 failures

Check from your laptop:

```bash
curl -si https://mcp.example.com/mcp | head -1          # 403: not from Anthropic, as intended
curl -si https://mcp.example.com/authorize | head -1    # 400: reaches the server, TLS works
```

## 7. Add it to Claude

1. Open **claude.ai > Settings > Connectors > Add custom connector**.
2. Name: `Freelancer`. Remote MCP server URL:

   ```
   https://mcp.example.com/mcp
   ```

3. Leave the OAuth client settings at their defaults. Claude registers itself automatically.
4. Click **Add**, then **Connect**. A page on `mcp.example.com` asks: "Allow access to your
   Freelancer.com account?" Enter your password and the authenticator code, then **Allow**.
5. On your phone, the connector appears in the Claude app under the same account. In a chat,
   enable it from the tools menu and ask, for example: "Search Freelancer for Python Telegram bot
   projects over $200."

`place_bid` and `send_message` are marked as write tools (not read-only, not idempotent), so
Claude asks before running them. If you change the connector's tool permissions, keep those two
on asking first.

## 8. Go live

Placing real bids needs an explicit switch. After testing `place_bid` in dry run on a real project
from Claude:

```bash
sudo sed -i 's/^MCP_DRY_RUN=true/MCP_DRY_RUN=false/' AGENT_DIR/.env
sudo systemctl restart freelancer-mcp
```

`MCP_MAX_BID_AMOUNT` stays as a ceiling on any single bid.

## Operations

| Task | Command |
| - | - |
| Sign every Claude client out | `sudo -u AGENT_USER AGENT_DIR/venv/bin/python mcp_server.py revoke-tokens` |
| Change password or authenticator | Run `init-auth` again, update `.env`, `systemctl restart freelancer-mcp` |
| Logs | `journalctl -u freelancer-mcp -f` |
| Update | `git pull`, `pip install -r requirements-mcp.txt`, `systemctl restart freelancer-mcp` |

If you think the password or the authenticator secret leaked, change both and run `revoke-tokens`.

## Optional: the Inspector against the public server, with OAuth

To test the real sign-in from the Inspector: in the Nginx config add `allow YOUR.LAPTOP.IP;` in
`location /`, set `MCP_ALLOW_LOOPBACK_REDIRECTS=true`, restart both, connect the Inspector to
`https://mcp.example.com/mcp` and follow its OAuth flow. Undo both changes afterwards.
