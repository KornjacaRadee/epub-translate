# EPUB Translate

EPUB Translate is a backend-first web app for translating EPUBs into different languages.

Even tho it was originally built to support translation from English to Serbian (Latin), the app supports all languages (some may require minor tweaks).

I recommend using the Gemini API for translation instead of LibreTranslate to achieve the best results.

LibreTranslate was implemented as an option to keep translation free and self-hosted, but the translation quality is not as high.

The app is built for a simple flow:

1. Create an account
2. Upload an English EPUB
3. Wait while the book is translated in the background
4. Download a translated EPUB with the original structure, styling, images, links, navigation, and metadata preserved as much as possible

This repository includes the web app, background worker, database migrations, Docker setup, and a self-hosted LibreTranslate path.

## What It Does

The goal of the project is to translate EPUBs while maintaining narrative flow and tone, adapting the text so it sounds natural in the selected language. The main focus is reliable EPUB translation.

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

## License

This project is open source under the MIT License. See [LICENSE](LICENSE).

## Local Self-Hosting

### 1. Edit the local compose file

Open `docker-compose.local.yml` and set at least a real `SECRET_KEY`, `DEFAULT_ADMIN_EMAIL`, and `DEFAULT_ADMIN_PASSWORD` directly in the `environment:` blocks. Add `GEMINI_API_KEY` if you want Gemini translations.

### 2. Start the stack

```bash
docker compose -f docker-compose.local.yml up -d
```

The local compose file uses `ENVIRONMENT=local`, so credits, Paddle checkout, pricing, and payment pages are disabled. Database migrations run automatically when the app container starts.

### 3. Optional: start LibreTranslate too

```bash
docker compose -f docker-compose.local.yml --profile libretranslate up -d
```

LibreTranslate is optional. The default local stack does not start it. If you use the profile, set `ENABLE_LIBRETRANSLATE` to `"true"` in the app and worker environment blocks.

### 4. Open the app

Visit:

- `http://localhost:8000`

### 5. Test the workflow

1. Register a user
2. Log in
3. Upload an English EPUB
4. Open the job page and watch progress
5. Download the translated EPUB when the job completes

## Pull-And-Run Local Deployment

Yes, this project can be run with prebuilt Docker images, so users do not need the source tree to build the app image themselves.

The app can use either LibreTranslate or Gemini 2.5 Flash Lite:

- If `GEMINI_API_KEY` is set, Gemini 2.5 Flash Lite appears as an engine and users can type any source and target language name.
- If LibreTranslate is enabled and reachable, LibreTranslate appears as an engine and the app shows the languages installed in that LibreTranslate instance.
- If only one engine is configured, only that engine is shown.
- LibreTranslate is optional and runs behind a Docker Compose profile.

To run without cloning this repository, create a new folder and add this `docker-compose.yml`:

```yaml
services:
  app:
    image: ghcr.io/kornjacaradee/epub-translate:latest
    command: uvicorn app.main:app --host 0.0.0.0 --port 8000
    environment:
      SECRET_KEY: replace-with-a-long-random-secret
      ENVIRONMENT: local
      DEFAULT_ADMIN_EMAIL: admin@example.com
      DEFAULT_ADMIN_PASSWORD: change-this-password
      ENABLE_LIBRETRANSLATE: "false"
      LIBRETRANSLATE_URL: http://libretranslate:5000
      LIBRETRANSLATE_API_KEY: ""
      GEMINI_API_KEY: ""
      GEMINI_MODEL: gemini-2.5-flash-lite
      GEMINI_BATCH_CHAR_BUDGET: "24000"
      RUN_MIGRATIONS: "true"
    ports:
      - "8000:8000"
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_started
    volumes:
      - ./uploads:/app/uploads
      - ./results:/app/results

  worker:
    image: ghcr.io/kornjacaradee/epub-translate:latest
    command: celery -A app.tasks.celery_worker worker --loglevel=INFO
    environment:
      SECRET_KEY: replace-with-a-long-random-secret
      ENVIRONMENT: local
      DEFAULT_ADMIN_EMAIL: admin@example.com
      DEFAULT_ADMIN_PASSWORD: change-this-password
      ENABLE_LIBRETRANSLATE: "false"
      LIBRETRANSLATE_URL: http://libretranslate:5000
      LIBRETRANSLATE_API_KEY: ""
      GEMINI_API_KEY: ""
      GEMINI_MODEL: gemini-2.5-flash-lite
      GEMINI_BATCH_CHAR_BUDGET: "24000"
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_started

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
    profiles: ["libretranslate"]
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

Create the folders used by the compose file if you want them present before first boot:

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

For Gemini-only mode, set `GEMINI_API_KEY` in the compose file and leave `ENABLE_LIBRETRANSLATE=false`.

Start the stack:

```bash
docker compose up -d
```

To start the optional LibreTranslate service too:

```bash
docker compose --profile libretranslate up -d
```

Also set `ENABLE_LIBRETRANSLATE=true` in the app and worker environment blocks.

Open the app at:

- `http://localhost:8000`


## Environment Variables

`.env` support is still there, but it is optional. For the simplest local setup, put values directly in `docker-compose.local.yml`. The app reads normal process environment variables, so Docker Compose can own the config directly.

Most settings already have code defaults. The ones users are most likely to override are:

- `SECRET_KEY`
- `DEFAULT_ADMIN_EMAIL`
- `DEFAULT_ADMIN_PASSWORD`
- `GEMINI_API_KEY`
- `ENABLE_LIBRETRANSLATE`
- `LIBRETRANSLATE_URL`
- `LIBRETRANSLATE_API_KEY`


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

## In Plain English

It is a self-hosted EPUB translation service. A user logs in, uploads an EPUB (in English or another language), the app translates the book into the selected language in the background, and the user downloads the translated EPUB once it is ready.
 
