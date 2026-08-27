# DevDB

> A simple, social movie and TV show tracker built for movie lovers who want to keep track of what to watch next and see what their friends are enjoying.

---

## 🍿 What is DevDB?

Have you ever spent 30 minutes scrolling through streaming platforms trying to decide what to watch, or forgotten that great movie recommendation your friend gave you last week? **DevDB** fixes that.

It is your personal digital movie hub designed to make choosing and tracking films effortless. Instead of clunky spreadsheets or bloated social networks, DevDB gives you a clean, distraction-free space to organize your watch history and share movie nights with your friends.

### What You Can Do

* **Queue Up Movie Nights**: Save movies and TV shows to your "Want To Watch" list so you always have a back-up plan for streaming night.
* **Track Your Library**: Keep a log of every title you’ve finished, rate them with stars, and jot down personal review notes.
* **See What Friends Are Watching**: Connect with buddies to check out their latest ratings and see what's trending in your friend group.
* **Find Shared Favorites**: DevDB automatically compares your wishlist with your friends' lists to highlight mutual matches—perfect for deciding what to watch together.
* **Instant Single-Click Updates**: Easily move items from your wishlist straight into your watched library with a single tap.

---

## 🤓 The Tech & Architecture

Under the hood, DevDB skips heavy JavaScript single-page-application (SPA) frameworks in favor of a fast, server-driven architecture powered by **FastAPI** and **HTMX**.

### Core Stack

* **Backend Framework**: Python 3.12 + FastAPI (Async route handlers)
* **Database ORM**: SQLAlchemy 2.0 (Async Engine with AsyncPG)
* **Dynamic Frontend**: HTMX 1.9+ (Server-side rendered HTML fragment swapping)
* **Styling**: Tailwind CSS (Dark theme with custom status badges)
* **Data Provider**: TMDB API v3 (Search, posters, and metadata hydration)
* **Containerization**: Docker Compose (App + PostgreSQL multi-container setup)

### Project Layout

```text
├── app/
│   ├── database.py         # Async engine & session factories
│   ├── main.py             # App initialization & router registration
│   ├── models.py           # SQLAlchemy schemas (User, WatchEntry, Friendship)
│   ├── routers/            # Feature-based API endpoints
│   │   ├── auth.py          # Session & authentication management
│   │   ├── buddies.py       # Activity feeds & mutual watchlist joins
│   │   ├── to_watch.py      # Wishlist view & card states
│   │   └── watch_entries.py # HTMX entry updates & quick status toggles
│   ├── services/
│   │   └── tmdb.py          # Formatted TMDB client service
│   └── templates/           # Jinja2 layouts & HTMX dynamic partials
├── docker-compose.yml
└── requirements.txt
```

### Quickstart & Development Setup

1. **Clone & Configure Environment**
   Create a `.env` file in the project root:
   ```env
   DATABASE_URL=postgresql+asyncpg://devdb_user:devdb_password@db:5432/devdb
   SECRET_KEY=your_secret_key
   TMDB_API_KEY=your_tmdb_api_key
   ```

2. **Launch Container Services**
   ```bash
   docker compose up --build
   ```
   Access the server at `http://localhost:8000`.

3. **Database Volume Reset**
   To flush test sessions, reset foreign keys, or start with fresh schemas:
   ```bash
   docker compose down -v
   docker compose up --build
   ```
