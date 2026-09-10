# DocFlow-AI Database Setup

## Local development

Local mode uses SQLite and creates the database from the SQLAlchemy metadata at
application startup. Copy the local template and start the API:

    copy /Y .env.example .env
    python -m uvicorn app.production_main:app --host 127.0.0.1 --port 8000 --reload

The local database is app.db unless DATABASE_URL is changed. Uploaded files
are stored below storage/uploads.

## Hosted PostgreSQL

Hosted mode requires PostgreSQL and an API key. Set these values in a private
.env file or through the deployment platform:

    DEPLOYMENT_MODE=hosted
    DATABASE_URL=postgresql+asyncpg://docflow_app:<password>@db:5432/docflow_ai
    DOCFLOW_API_KEY=<random-value-at-least-32-characters>

Apply the checked-in Alembic migration before starting the hosted API:

    alembic upgrade head
    alembic current

The production Compose file performs this migration as part of the API
container command. Do not run destructive database commands against a shared
database without a backup.

## Resetting local data

For a disposable local environment, stop the API and remove app.db and the
contents of storage/uploads. Do not use this procedure against hosted data.

## Scope limitation

This project stores jobs and documents for a trusted operator. It does not
provide user accounts, tenant isolation, or a distributed job queue.
