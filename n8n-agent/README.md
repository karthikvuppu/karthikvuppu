# Telegram agent for Gmail, Drive and the web (n8n + Claude)

Message your Telegram bot; Claude does the work in Gmail, Google Drive/Docs and a web browser, then replies.
Anything irreversible (send email, share or trash a file, submit a web form) waits for your **Approve / Decline** tap.

```
Telegram ──► n8n ──► Claude (AI Agent)
                       ├─ Gmail: search, read, draft
                       ├─ Drive: search · Docs: read, create, append
                       ├─ Browser service: open, read, click, fill   (public sites only)
                       └─ request_approved_action ─► asks you on Telegram ─► send / share / trash / submit
```

## What you need (all free except the server and API use)
| Item | Where | Cost |
|---|---|---|
| Server: Ubuntu 22.04/24.04, 2 vCPU, 4 GB RAM, public IP | Hetzner, DigitalOcean (Bangalore), AWS Lightsail (Mumbai), Oracle free tier | about ₹400-700/month |
| Free address `NAME.duckdns.org` | duckdns.org (sign in with Google) | free |
| Telegram bot token | Telegram, chat with **@BotFather** → `/newbot` | free |
| Anthropic **API** key | console.anthropic.com → API keys (a Claude chat subscription does not include API credit) | pay per use |
| Google OAuth client | console.cloud.google.com (steps below) | free |

Your Telegram ID (5814061609) is already the default in the setup script.

## Step 1 - Google OAuth client (once, about 5 minutes)
1. console.cloud.google.com → create a project.
2. **APIs & Services → Library**: enable **Gmail API**, **Google Drive API**, **Google Docs API**.
3. **OAuth consent screen**: User type *External*, fill the app name and your email. Add your own Google account under *Test users*.
   Later set *Publishing status → In production* (personal use, you will see an "unverified app" warning you can click through). Left in *Testing*, Google expires the login every 7 days.
4. **Credentials → Create credentials → OAuth client ID → Web application**.
   Authorized redirect URI: `https://NAME.duckdns.org/rest/oauth2-credential/callback` (use your DuckDNS name).
5. Copy the **Client ID** and **Client secret**.

## Step 2 - Install on the server
```bash
# copy this folder to the server (from your computer), then on the server:
cd n8n-agent
chmod +x setup.sh
./setup.sh
```
The script asks for: DuckDNS name and token, Telegram ID, bot token, Anthropic key, Google client ID/secret. Secret prompts are hidden; they go into n8n's encrypted credential store and are not kept in plain files.
It installs Docker, starts n8n + the browser service + Caddy (automatic HTTPS), imports the credentials and the two workflows.

## Step 3 - Finish in n8n (4 clicks)
1. On your computer: `ssh -L 5678:localhost:5678 USER@SERVER_IP`, then open http://localhost:5678 and create your owner account.
   (The editor is deliberately not on the internet; only the webhook paths are.)
2. **Credentials** → *Agent Gmail*, *Agent Drive*, *Agent Docs* → **Sign in with Google** for each.
3. Open workflow **Agent - Telegram Assistant** → switch **Active** on.
4. Message your bot on Telegram. First try: `show my 5 latest unread emails`.

## Using it
- "Find the email from the bank about the loan and summarise it"
- "Draft a reply to Ravi saying I'll send the documents tomorrow" → creates a **draft**
- "Send that draft to ravi@example.com" → you get an **Approve / Decline** message; tapping a button opens a small confirmation page in your browser, and the action runs.
- "Find the Drive file called MOU and share it with x@y.com as reader" → approval first.
- "Open example.com/pricing and tell me the plans"

## Safety design
- Only IDs in `ALLOWED_TELEGRAM_IDS` can command it. Anyone else just gets "Not authorized" with their own ID.
- The AI has **no direct** send/share/trash/submit tools. Those exist only inside the *Approved Actions* sub-workflow, behind the approval step. If you do not tap Approve within 10 minutes it is declined.
- Email, document and web content is treated as data, not instructions (prompt-injection guard in the system prompt).
- Browser service: needs an API key; refuses localhost, internal Docker hosts and cloud-metadata addresses; refuses password/card fields; its `/submit` endpoint also needs a token that only the approval workflow holds.
- n8n editor is bound to localhost; Caddy exposes only `/webhook/*`, `/webhook-waiting/*`, `/form-waiting/*` and the Google OAuth callback.
- Secrets live in `.env` (mode 600) and n8n's encrypted store. Back up `data/n8n` and keep `N8N_ENCRYPTION_KEY`; without it the saved credentials cannot be decrypted.

## Known limits (v1)
- Not included: permanently deleting mail, trashing mail, sending from other accounts, Calendar/Sheets (easy to add in the editor: drag a Gmail/Calendar tool onto the Agent).
- The browser runs on the server with no saved logins. It works for public pages; logged-in sites are not set up (Google is handled through the API, not the browser).
- `Doc Append Text` and the browser tools were checked against n8n's node definitions but not run end-to-end; if one misbehaves, open the node in the editor, press *Test step*, and fix the field it highlights.
- Each approval message shows the exact email/file details; read them before tapping Approve.

## Operating
```bash
docker compose logs -f n8n        # live log
docker compose ps                 # status
docker compose pull && docker compose up -d   # update (consider pinning the n8n image version first)
python3 build_workflows.py        # regenerate the workflow JSON, then re-import
python3 validate.py               # structural checks (set N8N_REF for parameter checks)
```
