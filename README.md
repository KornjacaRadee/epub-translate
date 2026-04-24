# EPUB Translate

EPUB Translate is a backend-first web app for turning English EPUB books into Serbian Latin while keeping the original EPUB structure as intact as possible.

The app is built for a simple flow:

1. Create an account
2. Upload an English EPUB
3. Wait while the book is translated in the background
4. Download a translated EPUB with the original structure, styling, images, links, navigation, and metadata preserved as much as possible

This repository includes the web app, background worker, database migrations, Docker setup, and a self-hosted LibreTranslate path.

## What It Does

The goal of the project is not a flashy frontend. The main focus is reliable EPUB translation.

Out of the box, the app gives you:

- email + password registration and login
- cookie-based session auth
- CSRF protection on forms
- EPUB-only uploads with file-size checks and sanitized filenames
- background translation jobs with progress tracking
- resumable batch processing for larger books
- PostgreSQL translation cache
- glossary support
- admin groundwork
- a global free-tier concurrency pool

## How Translation Works

At a high level, each book goes through this pipeline:

1. The EPUB is uploaded and stored safely on disk.
2. The worker reads the EPUB and extracts translatable XHTML content in reading order.
3. Content is classified into things like headings, body text, navigation, notes, captions, and link-heavy sections.
4. Small nearby segments can be merged for better context.
5. Translation batches are built using a character budget instead of a rigid fixed-count rule.
6. Terms protected by the glossary are preserved.
7. Translated text is normalized to Serbian Latin and cleaned for common mojibake issues.
8. The translated text is written back into the original EPUB structure.
9. The book is rebuilt and exposed for download.

The worker runs this as resumable steps, so bigger books are no longer forced through one giant task.

## Stack

- Python 3.12
- FastAPI + Jinja2
- SQLAlchemy 2.x + Alembic
- PostgreSQL
- Celery + Redis
- EbookLib + BeautifulSoup
- Docker Compose

## Local Development

### 1. Create your env file

Copy `.env.example` to `.env` and update the important values:

- `SECRET_KEY`
- `DEFAULT_ADMIN_EMAIL`
- `DEFAULT_ADMIN_PASSWORD`
- `SECURE_COOKIES=false` for plain local HTTP

### 2. Start the stack

```bash
docker compose up --build -d
```

### 3. Run database migrations

```bash
docker compose exec app alembic upgrade head
```

### 4. Open the app

Visit:

- `http://localhost:8000`

### 5. Test the workflow

1. Register a user
2. Log in
3. Upload an English EPUB
4. Open the job page and watch progress
5. Download the translated EPUB when the job completes

## Pull-And-Run Deployment

Yes, this project can be run as prebuilt Docker images so users do not need the source tree to build the app image themselves.

To run everything without cloning this repository, create a new folder and add this `docker-compose.yml`:

```yaml
services:
  app:
    image: ghcr.io/kornjacaradee/epub-translate:latest
    command: uvicorn app.main:app --host 0.0.0.0 --port 8000
    env_file: .env
    ports:
      - "8000:8000"
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_started
      libretranslate:
        condition: service_healthy
    volumes:
      - ./uploads:/app/uploads
      - ./results:/app/results

  worker:
    image: ghcr.io/kornjacaradee/epub-translate:latest
    command: celery -A app.tasks.celery_worker worker --loglevel=INFO
    env_file: .env
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_started
      libretranslate:
        condition: service_healthy
    volumes:
      - ./uploads:/app/uploads
      - ./results:/app/results

  redis:
    image: redis:7-alpine

  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: epub_translate
      POSTGRES_PASSWORD: postgres
      POSTGRES_USER: postgres
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres -d epub_translate"]
      interval: 5s
      timeout: 5s
      retries: 20
    volumes:
      - pgdata:/var/lib/postgresql/data

  libretranslate:
    image: ghcr.io/kornjacaradee/epub-translate-libretranslate:latest
    restart: unless-stopped
    ports:
      - "5000:5000"
    environment:
      LT_HOST: 0.0.0.0
      LT_PORT: 5000
      LT_THREADS: 4
    volumes:
      - ./models:/models:ro
      - libretranslate_data:/home/libretranslate/.local
    healthcheck:
      test: ["CMD", "python3", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:5000/languages', timeout=10).read()"]
      interval: 20s
      timeout: 10s
      retries: 10

volumes:
  pgdata:
  libretranslate_data:
```

Create the folders used by the compose file:

```bash
mkdir uploads results models
```

The `uploads` folder stores uploaded EPUB files, `results` stores translated EPUB files, and `models` is where optional local LibreTranslate / Argos language models go.

To enable a custom language model, put one or more `.argosmodel` files in the `models` folder before starting the stack:

```text
models/
  translate-en_sr.argosmodel
```

The `ghcr.io/kornjacaradee/epub-translate-libretranslate:latest` image imports `.argosmodel` files from `/models` when the container starts. Imported models are saved in the `libretranslate_data` Docker volume, so they stay available after restarts.

If you add a new `.argosmodel` later, restart LibreTranslate so it can import it:

```bash
docker compose restart libretranslate
```

Create a `.env` file in the same folder:

```bash
APP_NAME=EPUB Translate
ENVIRONMENT=production
DEBUG=false
SECRET_KEY=replace-with-a-long-random-secret
SESSION_COOKIE_NAME=epub_translate_session
SESSION_MAX_AGE_SECONDS=604800
CSRF_TOKEN_TTL_SECONDS=7200
SECURE_COOKIES=false
BASE_URL=http://localhost:8000

DATABASE_URL=postgresql+psycopg://postgres:postgres@postgres:5432/epub_translate
REDIS_URL=redis://redis:6379/0
LIBRETRANSLATE_URL=http://libretranslate:5000
LIBRETRANSLATE_TIMEOUT_SECONDS=60
LIBRETRANSLATE_RETRIES=3

UPLOAD_DIR=/app/uploads
RESULT_DIR=/app/results
MAX_UPLOAD_SIZE_BYTES=52428800
GLOBAL_FREE_ACTIVE_JOB_LIMIT=2

SOURCE_LANGUAGE=en
TARGET_LANGUAGE=sr
GLOSSARY_PATH=/app/glossary.example.yaml

DEFAULT_ADMIN_EMAIL=admin@example.com
DEFAULT_ADMIN_PASSWORD=change-this-password
```

Start the stack:

```bash
docker compose up -d
```

Run database migrations once after the containers are up:

```bash
docker compose exec app alembic upgrade head
```

Open the app at:

- `http://localhost:8000`


## Environment Variables

The main settings live in `.env`.

Important ones include:

- `DATABASE_URL`
- `REDIS_URL`
- `LIBRETRANSLATE_URL`
- `LIBRETRANSLATE_TIMEOUT_SECONDS`
- `GLOBAL_FREE_ACTIVE_JOB_LIMIT`
- `SOURCE_LANGUAGE`
- `TARGET_LANGUAGE`
- `GLOSSARY_PATH`
- `DEFAULT_ADMIN_EMAIL`
- `DEFAULT_ADMIN_PASSWORD`


## Translation Quality Notes

The app already includes several quality-focused protections:

- Serbian output is forced to Latin script
- common placeholder leaks are blocked
- glossary terms are protected using HTML no-translate spans
- merged translation units fall back to individual segment translation if structure is lost
- common mojibake patterns are cleaned before output is cached and written

That said, the translation backend is still the ceiling for quality. The EPUB pipeline can preserve structure well and reduce many failure modes, but if the translator itself is weak on a phrase, the output can still sound awkward.

## Glossary

The sample glossary file is:

- [glossary.example.yaml]
You can protect terms like:

- product names
- book-format words like `EPUB`
- brand names
- phrases you never want translated literally

## Tests

Run the test suite with:

```bash
python -m pytest -q
```

## Operational Notes

- Free users share a global active-job pool.
- There is no waitlist in v1.
- Pro and admin users bypass that free-tier pool limit.
- EPUB HTML is never rendered directly in the app UI.
- DRM-protected books are out of scope.
- Custom Argos `.argosmodel` files placed in `models/` are imported automatically by the LibreTranslate container and persist across restarts through the volume.

## In Plain English

It is a self-hosted EPUB translation service. A user logs in, uploads an English EPUB, the app translates the book to Serbian Latin in the background, and the user downloads a translated EPUB when it is done.
