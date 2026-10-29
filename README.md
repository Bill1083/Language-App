# Parlo

A self-hosted language-learning app for **French, Italian and Japanese**, taught in English, with
no paywall on the AI: you bring your own API keys.

- **Structured course** from A1 to C1 — 160 lessons per language, plus a hiragana/katakana module
  for Japanese. Lesson content is written by your LLM from the curriculum skeletons in
  [`curriculum/`](curriculum), validated, and stored, so each lesson is generated once.
- **AI conversation practice** — scenario role-plays, free chat, unit conversations and a tutor,
  by voice or text. Every one of your messages gets a feedback card (corrected sentence, inline diff,
  error types, a more natural version, approximate pronunciation flags), and each session ends with a
  summary.
- **Spaced repetition** (FSRS-5) for vocabulary, plus a Mistakes deck built from what you got wrong.
- **Audio everywhere**: text-to-speech for every word and sentence (each clip is cached and paid
  for once), and speech-to-text for answers you speak.
- Streaks, XP, daily goals, achievements, stats, an admin panel with usage and cost estimates,
  data export (JSON, CSV, Anki) and a PWA you can install on your phone.

## Quick start

```bash
cp .env.example .env
```

Fill in `APP_SECRET`, `POSTGRES_PASSWORD` and your AI keys (see [Configuration](#configuration)), then:

```bash
docker compose up -d --build
```

Open `http://127.0.0.1:7892` (or your domain once Nginx and HTTPS are set up — see
[DEPLOYMENT.md](DEPLOYMENT.md)). **The first account you create becomes the admin.** After that,
registration is invite-only by default: create invite links in **Admin → Users**.

Everything else is automatic: on start the API waits for Postgres, runs the Alembic migrations and
seeds the curriculum and scenarios. No manual database setup.

> **Microphone needs HTTPS.** Browsers only allow the mic on `https://` origins (and `localhost`).
> On the VPS that's the host Nginx + Certbot; see DEPLOYMENT.md.

### Before you use your Gemini key

Use the **paid tier** of the Gemini API (billing linked to the Google Cloud project). Free-tier prompts
and audio may be used to improve Google products and read by human reviewers; paid-tier data is not.
In [AI Studio](https://aistudio.google.com/apikey), confirm the key's project shows **Paid** before your
first conversation. Also set a **hard monthly spend limit** in each provider's billing console, in
addition to the app's own `DAILY_AI_BUDGET_USD`.

## Architecture

| Service  | What it does |
| -------- | ------------ |
| `caddy`  | Single entry point: `/api/*` → api, everything else → web. Published on `127.0.0.1:${PORT}` for the host Nginx; can do its own HTTPS (`docker-compose.standalone.yml`). |
| `web`    | Next.js 16 + React 19 + Tailwind 4 frontend (PWA). |
| `api`    | FastAPI: REST + the conversation WebSocket, auth, lesson engine, AI orchestration. |
| `worker` | arq worker: lesson generation and pre-generation, audio pre-caching, per-turn feedback, session summaries, recording cleanup, push reminders. |
| `db`     | PostgreSQL 18. |
| `redis`  | Job queue, rate limits, pub/sub for feedback events, small caches. |
| `tts`, `stt` | Optional self-hosted Kokoro TTS and faster-whisper STT (`--profile local-ai`, off by default). |
| `backup` | Optional nightly backups (`--profile backup`). |

Every service has a healthcheck and CPU/memory limits; with all AI in the cloud the stack idles well
under 2 GB and is capped at about 3.5 GB, so it shares a 4-vCPU / 16 GB VPS comfortably.

AI providers sit behind three interfaces (`api/app/providers/`): **LLM** (Gemini, Anthropic, OpenAI,
OpenRouter, any OpenAI-compatible server such as Ollama), **TTS** (Google Cloud, OpenAI, local, ElevenLabs,
Azure) and **STT** (Gemini, OpenAI, Groq, Deepgram, Google Cloud, local). All AI calls go through the
backend — keys never reach the browser — and every call is logged to `ai_usage` with an estimated cost.

## Configuration

All settings live in `.env` (copy `.env.example`; keep comments on their own lines — Docker Compose
reads `KEY=   # note` as the value `# note`). The provider, model and voice settings are defaults:
an admin can change them at runtime in **Admin → Providers** (stored in the database), test each one,
and compare voices side by side.

| Variable | Default | Meaning |
| --- | --- | --- |
| `DOMAIN` | `lang.wharveytech.com` | Public hostname (standalone Caddy HTTPS, push notifications). |
| `PORT` | `7892` | Host port Caddy is published on (127.0.0.1 only). |
| `APP_SECRET` | — | Long random string (`openssl rand -hex 32`). |
| `POSTGRES_PASSWORD` | — | Database password. Set before the first start. |
| `REGISTRATION_MODE` | `invite` | `open`, `invite` (admin creates links) or `closed`. The first account is always allowed. |
| `RECORDING_RETENTION_DAYS` | `30` | Voice recordings older than this are deleted nightly. |
| `STORE_RECORDINGS` | `true` | `false` keeps transcripts only; audio is deleted right after transcription. |
| `COOKIE_SECURE` | `auto` | Secure cookies from `X-Forwarded-Proto`; force with `true`/`false`. |
| `LLM_PROVIDER` | `gemini` | `gemini`, `anthropic`, `openai`, `openrouter`, `openai_compatible`. |
| `LLM_API_KEY` | — | Key for the LLM provider. |
| `LLM_BASE_URL` | — | For `openai_compatible` (e.g. Ollama `http://ollama:11434/v1`). |
| `LLM_MODEL_CONVERSATION` / `_FEEDBACK` / `_CONTENT` | provider default | Model per task: fast for replies, stronger for feedback, strongest for lesson generation. Gemini defaults to `gemini-3.8-flash` for all three. |
| `LLM_MODEL_FALLBACK` | provider default | Backup model used when the main one is overloaded (e.g. Gemini's 503 "high demand"). Gemini defaults to `gemini-3.5-flash-lite`; `off` disables it. |
| `TTS_PROVIDER_LESSON` / `_CONVERSATION` | `google` | `google`, `openai`, `local`, `elevenlabs`, `azure` — can differ. |
| `TTS_API_KEY` | — | Google Cloud API key restricted to Text-to-Speech… |
| `GOOGLE_APPLICATION_CREDENTIALS` | — | …or a service-account JSON in `./secrets`, e.g. `/secrets/google-tts.json`. |
| `TTS_BASE_URL`, `TTS_AZURE_REGION` | — | For local/OpenAI-compatible TTS and Azure. |
| `TTS_VOICE_FR` … `TTS_VOICE_JA_MALE` | Chirp 3 HD Aoede / Charon | Voices per language and gender. |
| `STT_PROVIDER` | `gemini` | `gemini`, `openai`, `groq`, `deepgram`, `google_cloud`, `local`. |
| `STT_API_KEY` | `LLM_API_KEY` if Gemini | Key for speech-to-text. |
| `STT_MODEL`, `STT_BASE_URL` | provider default | Model and server for STT. |
| `STT_COMBINED_FEEDBACK` | `false` | One Gemini call returns transcript + feedback + pronunciation notes. |
| `GEMINI_API_KEY`, `ANTHROPIC_API_KEY`, … | — | Optional extra keys, used when an admin switches provider at runtime. |
| `DAILY_AI_BUDGET_USD` | `2.00` | Per-user daily estimate cap (UTC day); admins are exempt. |
| `RATE_LIMIT_PER_MIN` | `30` | AI requests per user per minute. |
| `MAX_RECORDING_SECONDS` | `60` | Longest accepted voice message. |
| `PREGENERATE_AHEAD` | `3` | Lessons generated ahead of each learner. |
| `VAPID_*` | generated | Web-push keys; generated and stored on first boot if empty. |
| `BACKUP_KEEP`, `BACKUP_HOUR`, `BACKUP_PASSPHRASE` | `7`, `3`, — | Backup rotation, schedule and optional gpg encryption. |

Estimated costs (USD per million tokens / characters) are in `api/app/services/pricing.py` and are
editable through the admin config. They are estimates — check each provider's pricing page.

### Using local models instead

```bash
docker compose --profile local-ai up -d
```

Then in **Admin → Providers** set TTS to `local` with base URL `http://tts:8880/v1` and STT to `local`
with `http://stt:8000/v1`. On a CPU-only VPS this is slow and memory-hungry (each is capped at 2 GB);
cloud providers are the default for a reason.

## Adding a new language

1. **Write the skeleton**: copy `curriculum/fr.yaml` to `curriculum/<code>.yaml` (e.g. `es.yaml`) and
   rewrite it — `language`, `name`, and for each CEFR level 8–12 units of 4–6 lessons, each lesson with
   `objectives`, `vocab` (nouns with their article) and `grammar`. Quote YAML values that contain a
   comma, a colon followed by a space, or words YAML reads as booleans (`"no"`, `"yes"`, `"on"`).
2. **Register it** in the backend: add the code to `COURSE_FILES` in
   `api/app/services/curriculum.py`, a row to `LANGUAGES` (name, city, country) and a rule to
   `LANGUAGE_RULES` in `api/app/services/languages.py`, and its locale to `LOCALES` and default voices
   to `DEFAULT_VOICES` in `api/app/providers/tts.py` (and `LANG_NAMES`/`LOCALES` in `providers/stt.py`).
3. **Register it** in the frontend: add it to `LANGS` (name, native name, accent characters) in
   `web/src/lib/languages.ts`, a flag in `web/src/components/flag.tsx`, an accent colour under
   `[data-lang="<code>"]` in `web/src/app/globals.css`, and widen the `Lang` type in `web/src/lib/types.ts`
   and the `^(fr|it|ja)$` patterns in `api/app/routers/audio.py` and `admin.py`.
4. Run the curriculum tests (`docker compose --profile test run --rm api-test`) and rebuild:
   `docker compose up -d --build`. The seeder creates the levels, units and lessons on start; content is
   generated the first time each lesson is opened.

Changing an existing YAML lesson is safe at any time: on the next start its skeleton hash changes and
the lesson is regenerated on its next visit (unless an admin hand-edited it).

## Backups

```bash
./scripts/backup.sh
```

writes `backups/db-<timestamp>.dump` (pg_dump, custom format) plus tarballs of the recordings and the
audio cache, keeping the newest `BACKUP_KEEP` of each. Set `BACKUP_PASSPHRASE` to encrypt them with gpg.
Run it nightly from the host's crontab:

```bash
crontab -e
```

```cron
15 3 * * * cd /home/deploy/parlo && ./scripts/backup.sh >> backups/backup.log 2>&1
```

or let a container do it with `docker compose --profile backup up -d` (unencrypted, at `BACKUP_HOUR`
UTC). Restore with:

```bash
./scripts/restore.sh 20261028-031500
```

Copy `./backups` off the server (encrypted) as well — a backup on the same disk doesn't survive the disk.

## Development

API, worker, database and Redis in Docker, Next.js on the host with hot reload, both behind Caddy at
`http://localhost:7892`:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build
```

```bash
cd web && npm install && npm run dev
```

(The dev server uses port 3456 — `Caddyfile.dev` forwards to it.)

Backend tests (answer checking, FSRS scheduling, feedback schema validation, provider adapters
against mocked HTTP, curriculum and kana validity):

```bash
docker compose --profile test run --rm --build api-test
```

Frontend type check:

```bash
cd web && npm run typecheck
```

New database migration after changing `api/app/models.py`:

```bash
docker compose run --rm -v "$PWD/api/alembic/versions:/app/alembic/versions" api alembic revision --autogenerate -m "describe the change"
```

Design notes and every decision the spec left open are in [DECISIONS.md](DECISIONS.md).

## Privacy

- Recordings are uploaded to the STT provider for transcription only; with `STT_COMBINED_FEEDBACK=true`
  the same provider (Gemini) also returns feedback from that request.
- Google Cloud TTS only ever receives the AI's text.
- The microphone is push-to-talk only: it is opened when you hold or tap the mic and released straight after.
- Users can delete single conversations (with their recordings) or all their recordings in Settings.
- Recordings and the database live on your VPS, so server hardening matters most: SSH keys only, a
  firewall, unattended security updates, and encrypted off-site backups.
