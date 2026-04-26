# Dashy — Claude Code Project Context

## What is Dashy?
Dashy is a personal dashboard and productivity system built by Steve Vinter (steve.vinter@gmail.com). It combines billing/coaching practice management, a personal library (Libby), a family calendar (Glance), and a mobile PWA companion (Mobly). It is a fork of a dashboard originally built by Rich Whitcomb (richwhitjr/dashboard).

## Key People
- Steve Vinter — owner, solo developer (with Cody)
- Rich Whitcomb — upstream fork author (Osmo, AW company)

## Tech Stack
- **Backend:** Python/FastAPI, SQLite via SQLAlchemy, Alembic migrations
- **Frontend:** React/TypeScript, Vite, Tufte CSS aesthetic
- **Mobile:** SvelteKit PWA (Mobly), served at /m via FastAPI StaticFiles
- **Database:** ~/.personal-dashboard/dashboard.db
- **Config:** ~/dashy/dashy_install.json (secrets/install), ~/dashy/dashy_config.json (operational)
- **Billing seed:** ~/dashy/dashy_billing_seed.json
- **Sidebar config:** ~/dashy/sidebar.config.json

## Key File Locations
- Backend: app/backend/
- Frontend: app/frontend/src/
- Mobly: mobile/src/
- Routers: app/backend/routers/ (billing.py, coaching.py, libby.py, mobile.py, etc.)
- Alembic migrations: alembic/versions/
- Obsidian vault: /Users/stevevinter/Obsidian/MyNotes/
- Project specs: /Users/stevevinter/Obsidian/MyNotes/Projects/ (one subfolder per project)
- Meeting notes: /Users/stevevinter/Obsidian/MyNotes/8 Meetings/
- API keys: ~/.personal-dashboard/config.json
- Logs: /tmp/dashboard-backend.log, /tmp/dashboard-frontend.log

## Make Targets
- `make dev` — start backend (port 8000) + frontend (port 5173) — run in shell
- `make restart` — stop + restart both servers — run in shell
- `make stop` — stop all servers — run in shell
- `make checkpoint "comment"` — git add + commit — run at end of each Cody session
- `make release VERSION=x.y.z` — build DMG, tag GitHub release — run in shell
- `make mobile-build` — rebuild Mobly PWA — required after any mobile/ changes
- `make db-upgrade` — run pending Alembic migrations
- `make mobile-set-password p=yourpass` — set Mobly login password

## Development Conventions
- Request numbering: sequential r1, r2... per Cody session, reset each new session
- Put "Request rN — description" at top of each prompt
- After each request, copy summary to clipboard:
  cat << 'EOF' | pbcopy
  rN — description
  summary here
  EOF
- Always run make checkpoint after completing a batch of requests
- Always run npm run build before make release to catch TypeScript errors
- When adding Alembic migrations: use date-prefixed filenames e.g. 20260424_0001_description.py

## Architecture Notes
- Tailscale IP: 100.71.212.125 (bostondesktop)
- Mobly HTTPS via Tailscale Serve: https://bostondesktop.taild60ba0.ts.net/m
- CORS allows Tailscale IP alongside localhost
- Uvicorn binds to 0.0.0.0 (all interfaces) for Tailscale access
- Session cookie auth for Mobly (SameSite=Lax, no Secure flag — HTTP over Tailscale)
- In-memory token store (_active_tokens) — cleared on restart, 90-day session lifetime

## Key Data Model Facts
- billing_clients: status TEXT ('active'/'infrequent'/'inactive'), not boolean active
- billing_sessions: canceled BOOLEAN, dismissed BOOLEAN, is_confirmed BOOLEAN
- calendar_events: attendees_json TEXT (JSON array of {email, name, response})
- library_entries: type_code TEXT ('b'=book, 'a'=article, 'v'=video, 'p'=podcast, 'n'=note)
- Client-to-event matching: use _find_client_for_event() — email-first, name fallback
- Claude API usage: logged to claude_usage_log table via claude_utils.py

## Project Specs (read before working on a module)
- Dashy: Projects/Dashy/
- Mobly: Projects/Mobly/Mobly-spec.md (includes Glance three-mode plan)
- Libby: Projects/Libby/
- Glance: Projects/Glance/
- Vinny: Projects/Vinny/

## Mobly Current State
- Two screens: Libby (search/add/share/notes/covers) and Glance (PIL monthly PNG)
- Bottom nav: 📚 Libby / 📅 Glance
- Glance: server-rendered PNG at GET /api/mobile/glance/render?start=YYYY-MM-DD&weeks=8
- Three-mode plan: Mode 1 (PNG, done) → Mode 2 (week cards) → Mode 3 (create) — see Mobly spec

## Google OAuth
- Token: ~/.personal-dashboard/.google_token.json
- Scopes: drive, gmail, calendar, docs, spreadsheets
- Re-authenticate via Settings → Connectors → Google if token expires
- prompt=consent, access_type=offline in OAuth flow

## Daily Scheduled Jobs (sync.py)
- 7am ET: daily digest email + synopsis pre-warming for next 48hr meetings
- Business hours (8am-6pm ET): Granola sync every 30min at :05
- After hours: Granola sync every 2hrs
- Canceled session detection: runs after every calendar sync
