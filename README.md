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

For pull-based deployment, also set:

- `APP_IMAGE`
- `LIBRETRANSLATE_IMAGE`

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
