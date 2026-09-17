# Architectural Timeline

Point it at a public GitHub repo. Claude builds a three-tier architecture map
(system → module → code snippet) for the newest tags, and a slider lets you travel
between tags to see how the architecture shifted. Three panes: diagram, code, chat.

## Local

```bash
cd api && python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt && cd ..
cd frontend && npm install && cd ..
cp .env.example .env
make dev                        # Flask on :5000, Vite on :5173
```

### Authentication

The Anthropic SDK resolves credentials itself, in this order: `ANTHROPIC_API_KEY`,
`ANTHROPIC_AUTH_TOKEN`, then an OAuth profile created by the `ant` CLI. Either works:

- **OAuth (recommended locally)**: `brew install anthropics/tap/ant`, then `ant auth login`.
  A browser window completes the login and stores a profile under `~/.config/anthropic/`.
  Leave `ANTHROPIC_API_KEY` unset; an exported key, even an empty one, always wins over
  the profile. `ant auth status` shows which source is active; use `ANTHROPIC_PROFILE=<name>`
  to select a named profile.
- **API key**: set `ANTHROPIC_API_KEY` in `.env`.

The header of the UI and `GET /api/health` report which source the backend picked up.

### Model

`ARCH_MODEL` selects the model for generation and chat. The default is `claude-sonnet-5`;
set `claude-opus-5` for higher-quality graphs at roughly 2.5x the cost.

Open http://localhost:5173, paste a repo URL, press Load. The newest three tags are
generated oldest → newest. Drag the slider to an ungenerated tag and press **Generate**.

Or from the CLI:

```bash
make generate URL=https://github.com/owner/repo TAGS=3
cd api && .venv/bin/python -m app.cli list
```

Repos with pre-release or per-package tags (monorepos) may need a tag filter so the newest
three tags form one release train; the CLI takes a regex:

```bash
cd api && .venv/bin/python -m app.cli generate https://github.com/vitejs/vite --tags 3 --tag-pattern '^v[0-9]+\.[0-9]+\.[0-9]+$'
```

## Features

- **Incremental generation**: each inventory row stores the file's git blob hash. When a
  component or module has the same paths and byte-identical files as the nearest generated
  tag, its modules or snippets are copied from that tag instead of calling the model, so a
  patch release costs a fraction of a fresh tag. Run `app.cli rehash` once for inventories
  created before hashing existed.
- **Overview on load**: the newest tag of every generation job also gets its written
  overview, so a freshly loaded repo opens with the diagram and the walkthrough.

- **Three tiers**: system → module → code snippet. Click a node to zoom in; the breadcrumb zooms out.
- **Time machine**: a slider over every tag. Drag to an ungenerated tag and press Generate.
- **Compare mode**: press *compare* in the header. The slider grows a second thumb for the
  earlier tag; nodes and edges are colored added / removed / changed, removed items appear
  as ghosts, and the banner shows counts. *Summarize changes* asks the model for a short
  narrative of the transition (one call, cached). *Ask what changed* sends the diff to chat.
- **Chat**: grounded in the generated graph plus read-file tools over the repo at that tag.
  Citations like `path:12-40` open the code pane. The `?` on any node pre-fills a question.
- **Intro page, light/dark**: the landing page explains the tool and lists generated repos;
  the theme toggle persists per browser (light by default).

## Public demo settings

- `DEMO_MODE=1` disables loading new repositories and generating new tags (the UI shows
  why). Chat, overviews and change summaries stay on.
- Model-calling endpoints are rate limited per client IP with a leaky bucket: burst
  `LLM_RATE_CAPACITY` (10), then one call per `LLM_RATE_LEAK_SECONDS` (20). Over the limit
  returns 429 with `Retry-After`. `RATE_LIMIT_ENABLED=0` turns it off (the tests do).
- `GITHUB_TOKEN` lets the generator clone, tarball, and read files from private repos, and
  raises the GitHub API rate limit. It is sent as a per-command header, never written to
  `.git/config`.

## Tests

```bash
make test        # pytest (LLM mocked) + tsc

# same suite against Postgres, to catch dialect issues before deploying
docker run -d --name arch-pg -e POSTGRES_PASSWORD=pw -e POSTGRES_DB=arch -p 55432:5432 postgres:16
TEST_DATABASE_URL=postgres://postgres:pw@localhost:55432/arch make test-api
```

## Vercel

`vercel.json` defines two [Services](https://vercel.com/docs/services) in one project: `web`
(the Vite build in `frontend/`) and `api` (Flask in `api/`, entrypoint `index:app`, deps from
`api/requirements.txt`). Top-level rewrites send `/api/*` to the Flask service, which sees
the full path, and everything else to the static frontend. The Flask function runs on Fluid
compute with `maxDuration` 300 s (the Hobby plan maximum). Python 3.12 is Vercel's default.

1. Create the project from this repo; add a Postgres store (Neon via the Marketplace).
2. Environment variables: `DATABASE_URL` (from the store), `ANTHROPIC_API_KEY` (there is no
   browser login on a serverless function), `FILE_SOURCE=github`, and one of:
   - `GENERATION_MODE=chunked` to generate on Vercel (see below), or
   - `GENERATION_MODE=off` for a view-only deployment populated from your machine.

   On Vercel (`VERCEL=1` is set by the platform) `FILE_SOURCE` defaults to `github` and
   `GENERATION_MODE` to `chunked`, so only `DATABASE_URL` and `ANTHROPIC_API_KEY` are
   strictly required. `POSTGRES_URL` is accepted as an alias for `DATABASE_URL`.

### Migrating and syncing the Vercel database

The schema is created on first request, but you can prepare it explicitly, and copy what
you generated locally (sqlite) into Postgres. Pull the connection string with the Vercel
CLI, then:

```bash
npx vercel env pull .env.vercel --environment=production   # DATABASE_URL_UNPOOLED is best for DDL
DB=$(grep '^DATABASE_URL_UNPOOLED=' .env.vercel | cut -d= -f2- | tr -d '"')
make migrate DB="$DB"                       # create/upgrade tables, safe to re-run
make sync DB="$DB"                          # copy repos, tags, graphs, inventories, summaries
make sync DB="$DB" REPO=psf/requests        # one repo only
```

The sync matches rows on natural keys (repo url, tag name, file path), replaces each tag's
graph and inventory, never copies jobs, and is safe to re-run. Preview and production
share one database unless you attach separate stores, so one sync serves both.

File contents are never stored. Locally they come from the clone (`git show`); on
Vercel from raw.githubusercontent.com by commit sha.

### Chunked generation on Vercel

A serverless function cannot run for the minutes a full generation takes, and has no git.
In chunked mode the generator is a resumable state machine: every unit of work (inventory,
the tier 1 call, a batch of tier 2 or tier 3 calls, the final write) saves its progress in
the `generation_jobs.state` column. `POST /api/jobs/<id>/step` runs as many units as fit in
`STEP_BUDGET_S` seconds (default 150; a step can overrun by one batch of calls, which stays under the 300 s `maxDuration` in `vercel.json`) and
returns. The browser keeps calling step until the job reports done, so a generation only
progresses while a tab is open on it. Sources come from the GitHub tarball for the commit,
extracted under `/tmp` and reused while the instance is warm; tags come from the GitHub
API (unauthenticated: 60 requests/hour; set `GITHUB_TOKEN` to raise that).

The same state machine runs locally, where a background thread simply loops the steps.

## Layout

- `api/app/ingest` — git clone/tags/tree, inventory filters, file source abstraction
- `api/app/llm` — `prompts.py` (cached Jinja templates in `prompts/`), `generate.py` (the three tiers and repair), `jobs.py` (resumable job state machine), `runner.py`, `chat.py`, `overview.py`
- `api/app/routes` — REST + SSE chat
- `frontend/src` — Zustand store, React Flow + ELK diagram, Monaco code pane, rc-slider timeline, chat
