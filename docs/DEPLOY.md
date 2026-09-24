# Deploying to a VPS

One small server runs the whole stack with Docker Compose: PostgreSQL, Redis,
Django (gunicorn), Celery worker and beat, the Telegram bot, nginx with the
React build, and Caddy in front for HTTPS. About €4–6/month (Hetzner CX22,
DigitalOcean Basic 2 GB or similar).

```
Internet ──443──> Caddy (HTTPS, certificates) ──> nginx (React, /media) ──> Django/gunicorn
                                                                      │
                                        PostgreSQL · Redis · Celery worker/beat · Telegram bot
```

## 1. Server and domain

1. Create a VPS with **Ubuntu 24.04**, at least **2 GB RAM**, and add your SSH key.
2. Point a domain (or subdomain) at it: an **A record** `pcbuilder.example.com → <server IP>`.
   Without a domain the site still runs over plain HTTP on the IP, but then skip Caddy
   (use `docker compose up -d` with the base file only) and keep `SECURE_COOKIES=0`.
3. Open only ports 22, 80 and 443:

   ```bash
   ufw allow OpenSSH && ufw allow 80 && ufw allow 443 && ufw enable
   ```

## 2. Docker

```bash
curl -fsSL https://get.docker.com | sh
```

## 3. Code and configuration

```bash
git clone https://github.com/DAROLEND/PC-Builder.git && cd PC-Builder
cp .env.example .env
nano .env
```

Fill in at least:

| Variable | Value |
|---|---|
| `DOMAIN` | `pcbuilder.example.com` |
| `DJANGO_SECRET_KEY` | output of `python3 -c "import secrets; print(secrets.token_urlsafe(50))"` |
| `DJANGO_ALLOWED_HOSTS` | `pcbuilder.example.com,localhost,backend` |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | `https://pcbuilder.example.com` |
| `FRONTEND_URL` | `https://pcbuilder.example.com` |
| `SECURE_COOKIES` | `1` |

Optional: `ANTHROPIC_API_KEY` (AI advisor through Claude; `ADVISOR_DAILY_LLM_LIMIT`
caps the calls per day), `TELEGRAM_BOT_TOKEN` (price alerts). Keep
`MARKET_FETCH_ENABLED=0`: collecting data from hotline.ua needs the
administration's written permission (user agreement, p. 6.4). The public demo
runs on the curated catalog that ships with the repository.

`.env` holds secrets: it is in `.gitignore`, never commit it.

## 4. Start

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.yml -f docker-compose.prod.yml ps
```

The first start applies migrations and loads the demo catalog (65 parts, 5 public
builds, the `demo` / `demo12345` account). Caddy fetches the HTTPS certificate on
the first request; give it a minute. Then open `https://pcbuilder.example.com`.

Admin account:

```bash
docker compose exec backend python manage.py createsuperuser
```

Once HTTPS works, set `SECURE_HSTS_SECONDS=31536000` in `.env` and run the
`up -d` command again.

## 5. Updates

```bash
git pull
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

Migrations run automatically on start of the `backend` container.

## 6. Backups

The database lives in the `pgdata` volume, photos in `media`. A nightly dump:

```bash
mkdir -p ~/backups
crontab -e
# 03:30 every night, keep 14 days
30 3 * * * cd ~/PC-Builder && docker compose exec -T db pg_dump -U pcbuilder pcbuilder | gzip > ~/backups/pcbuilder-$(date +\%F).sql.gz && find ~/backups -mtime +14 -delete
```

Restore: `gunzip -c backup.sql.gz | docker compose exec -T db psql -U pcbuilder pcbuilder`.

## 7. Logs and troubleshooting

```bash
docker compose logs -f backend          # Django / gunicorn
docker compose logs -f worker beat      # background tasks
docker compose logs -f caddy            # certificates, HTTPS
```

| Symptom | Likely cause |
|---|---|
| `ImproperlyConfigured: Set DJANGO_SECRET_KEY` | `.env` is missing the key; the server refuses to start with the default one on purpose |
| 400 Bad Request | the domain is not in `DJANGO_ALLOWED_HOSTS` |
| 403 CSRF on the admin login | `DJANGO_CSRF_TRUSTED_ORIGINS` must be `https://<domain>` |
| No certificate | the A record does not point at the server yet, or port 80/443 is closed |

## Free hosting: Render + Supabase

Good enough for a portfolio demo. `render.yaml` describes the services.

1. **Supabase:** create a project in the region **Central EU (Frankfurt)**.
   Open **Connect** and copy the **Session pooler** URI, then append
   `?sslmode=require`:
   `postgresql://postgres.<ref>:<password>@aws-0-eu-central-1.pooler.supabase.com:5432/postgres?sslmode=require`.
   The direct connection is IPv6-only and not reachable from Render. If the
   password contains `@ # / :`, percent-encode those characters.
2. **Render:** New → Blueprint → this repository. Paste the URI into
   `DATABASE_URL`; `ANTHROPIC_API_KEY` is optional (without it the advisor
   uses the rule-based planner). The first deploy migrates and loads the demo
   catalog.
3. If Render assigned the API another hostname (the name was taken), update
   the `/api/*` rewrite destination and `FRONTEND_URL` in `render.yaml` and push.
4. Set the repository variable `DEMO_API_URL` to the API URL: the
   *Keep demo alive* workflow then queries it daily, so Supabase does not
   pause the project after a week of inactivity.

Free-plan limits: the API sleeps after 15 idle minutes (the first request then
takes up to a minute); background workers are paid, so Celery tasks run inline
(`CELERY_TASK_ALWAYS_EAGER=1`), the NBU rate is refreshed on every start, and
the Telegram bot does not run. The container disk is ephemeral, so uploaded
media do not survive a restart.

## What the configuration does

- **Secrets and debug:** with `DJANGO_DEBUG=0` Django refuses to start with the
  repository's placeholder key.
- **HTTPS:** Caddy terminates TLS and renews certificates; nginx passes
  `X-Forwarded-Proto` through, so Django marks cookies `Secure` and CSRF checks
  the right origin.
- **Only Caddy is exposed:** the prod override removes the published ports of
  `backend` (8000) and `frontend` (8080).
- **Photos** are served by nginx from the shared `media` volume, not by Django.
- **Abuse limits:** sign-up 10/hour and login 30/hour per IP, the AI advisor
  10 requests/hour per user plus a site-wide daily cap on Claude calls.
- **Payments** stay on the fake provider unless `PAYMENT_PROVIDER=stripe` with
  test keys.
