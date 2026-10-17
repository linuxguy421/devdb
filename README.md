# DevDB

Personal media tracker for movies and TV shows. Search [TMDB](https://www.themoviedb.org/), keep a private watchlist, track progress, rate titles, share recommendations with buddies, and see how your library is growing.

Built with **FastAPI**, **SQLAlchemy (async)**, **PostgreSQL**, **Jinja2**, **HTMX**, and **Tailwind CSS**.

---

## Features

| Area | What you get |
|------|----------------|
| **Search** | TMDB-backed discovery of movies and TV shows |
| **My Media** | Watchlist with statuses: *want to watch*, *in progress*, *watched* |
| **TV progress** | Season/episode cursor with next-episode advancement |
| **Ratings & notes** | Personal 1–10 ratings and optional notes |
| **Stats** | Completion rates, genre breakdowns, monthly completion trends, release decades, milestones, time watched |
| **What to Watch** | Recommendation picks from your list, discover, or buddy activity |
| **Buddies** | Friend requests, shared activity, mutual watchlists, title recommendations |
| **Profile** | Avatar, bio, recovery codes, account settings |
| **Admin** | User management, audit log, instance health (admins only) |
| **Security** | Session cookies, CSRF protection, recovery codes for account recovery |

---

## Requirements

- [Docker](https://docs.docker.com/get-docker/) and Docker Compose v2
- A free [TMDB API key](https://www.themoviedb.org/settings/api) (required for search, posters, and title details)

Optional helper: `./devdb.sh` can install Docker/Compose on common Linux distros and manage the stack.

---

## Quick start

### 1. Clone and configure

```bash
git clone https://github.com/linuxguy421/devdb.git
cd devdb
cp .env.example .env
```

Edit `.env` and set at least:

| Variable | Notes |
|----------|--------|
| `POSTGRES_PASSWORD` | Strong password for PostgreSQL |
| `SECRET_KEY` | Long random string used for sessions |
| `TMDB_API_KEY` | Your TMDB v3 API key |
| `TMDB_READ_ACCESS_TOKEN` | Optional TMDB v4 read access token |
| `ADMIN_USERNAMES` | Optional: comma-separated usernames promoted to admin on next login |
| `SUPER_ADMIN` | Optional: single username that is always admin and cannot be demoted or disabled |

### 2. Start the stack

```bash
docker compose up -d --build
```

Or with the helper script:

```bash
chmod +x devdb.sh
./devdb.sh --up
```

Compose starts PostgreSQL, runs Alembic migrations to head, then starts the app on **http://localhost:8000**.

### 3. Health checks

```bash
curl -fsS http://localhost:8000/healthz   # {"status":"ok"}
curl -fsS http://localhost:8000/readyz    # {"status":"ready"} when DB is reachable
```

---

## Administrator

Admin tools are available only to users with `is_admin`. An **Admin** link appears in the navbar for those accounts.

### Bootstrap your first admin

1. Register (or use an existing account).
2. Set one or both of these in `.env`:

```bash
# Promote these users to admin the next time they log in
ADMIN_USERNAMES=alice,bob

# Root account: always admin; cannot be demoted or disabled via the UI
SUPER_ADMIN=alice
```

3. Restart the app if it was already running so settings reload.
4. Log in as that username — the admin flag is applied on successful login.

`SUPER_ADMIN` is case-insensitive and takes a **single** username. Prefer setting it for the account you never want locked out.

### Pages

| Path | Purpose |
|------|---------|
| `/admin` | Dashboard: user/media counts, DB health, logins in last 7 days, recent audit |
| `/admin/users` | Search/filter users; quick enable/disable and promote/demote |
| `/admin/users/{id}` | User detail: account info, library breakdown, recent watches, related audit, actions |
| `/admin/audit` | Audit log with filters (action, actor, target, date range) |

### What admins can do

- **Enable / disable** accounts (disable blocks login; username and email stay taken — no hard delete)
- **Promote / demote** administrators
- Optional **disable reason** on the user detail page (stored in the audit log and shown on the Account panel when the user is disabled)
- View **last login** times and watch-entry activity per user

### Safety rules

- You cannot disable or change the admin role of **your own** account.
- You cannot demote the **last** remaining administrator.
- The **`SUPER_ADMIN`** user cannot be demoted or disabled under any circumstance (UI shows *locked*).
- Disabled users cannot log in; existing sessions are treated as logged out.

### Audit trail

Admin actions (`user.enabled`, `user.disabled`, `user.promoted`, `user.demoted`) are written to `admin_audit_logs`. Open **Audit** or the **Related audit** section on a user detail page. Filter by action or target username as needed.

---

## Helper script (`devdb.sh`)

| Command | Purpose |
|---------|---------|
| `./devdb.sh --install` | Install Docker Engine + Compose (Debian/Ubuntu, RHEL/Fedora, openSUSE, Arch, …); create `.env` from example; print TMDB setup notes |
| `./devdb.sh --up` | Build and start the stack |
| `./devdb.sh --down` | Stop the stack |
| `./devdb.sh --update` | `git pull` current branch and rebuild/restart |
| `./devdb.sh --logs` | Follow app container logs |
| `./devdb.sh --status` | Show Compose service status |
| `./devdb.sh --uninstall` | Tear down containers/volumes (optional Docker + directory removal) |

---

## Architecture (high level)

```
Browser  →  FastAPI (Jinja2 + HTMX)  →  PostgreSQL
                 ↓
              TMDB API (search / details / posters)
```

- **`app/routers/`** — HTTP routes (pages, auth, admin, titles, watch entries, buddies, profile, stats, what-to-watch)
- **`app/services/`** — TMDB client, media sync, TV progress, stats aggregation, recommendations
- **`app/models.py`** — SQLAlchemy models (`User`, `MediaItem`, `WatchEntry`, `TVSeason`, `AdminAuditLog`, friendships, recommendations, …)
- **`alembic/`** — Schema migrations (applied by the `migration` Compose service before the app starts)

---

## Configuration

Settings are loaded from the environment (see `.env.example`). Important keys:

| Key | Default / notes |
|-----|------------------|
| `DATABASE_URL` | Async PostgreSQL URL (`postgresql+asyncpg://…`) |
| `SECRET_KEY` | Required; session signing |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Session lifetime |
| `DEBUG` | Must be `False` in production |
| `ENVIRONMENT` | `development` or `production` |
| `COOKIE_SECURE` | Must be `True` when `ENVIRONMENT=production` |
| `TMDB_API_KEY` | Required for media features |
| `ADMIN_USERNAMES` | Comma-separated usernames promoted to admin on next successful login |
| `SUPER_ADMIN` | Single username that is always admin and cannot be demoted or disabled |

Production validation rejects insecure combinations (`DEBUG=True` or `COOKIE_SECURE=False` with `ENVIRONMENT=production`).

---

## Development

### Local (without Docker)

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
# Point DATABASE_URL at a reachable Postgres instance
alembic upgrade head
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Tests

```bash
# Preferred: run inside the built app image
docker compose run --rm app pytest -q

# Or locally with a test DB / aiosqlite setup as used by the suite
pytest -q
```

---

## Deployment notes

Normal Compose sequence:

```bash
docker compose up -d postgres
docker compose run --rm migration
docker compose up -d app
```

For release checklists, backups, and rollback procedure, see **[RELEASE_OPERATIONS.md](RELEASE_OPERATIONS.md)**.

---

## Project layout

```
.
├── app/                 # Application code
│   ├── main.py          # FastAPI entrypoint
│   ├── models.py
│   ├── routers/         # includes admin.py
│   ├── services/
│   ├── templates/       # includes templates/admin/
│   └── static/
├── alembic/             # Database migrations
├── tests/
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
├── devdb.sh             # Ops helper
├── RELEASE_OPERATIONS.md
└── .env.example
```

---

## License

Private / personal project unless otherwise noted in the repository.
