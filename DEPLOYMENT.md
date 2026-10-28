# Deploying Parlo to the VPS

The same box and flow as the other apps: Docker behind the host's Nginx + Certbot, here at
`https://lang.wharveytech.com` (change the name if you like). Ports 7888–7891 are taken, so Parlo
uses **7892**.

**You need:** a Gemini API key on a **paid** Google Cloud project (<https://aistudio.google.com/apikey>),
and for speech a Google Cloud API key restricted to the **Cloud Text-to-Speech API** (or a service-account
JSON). Gemini and Text-to-Speech can share one project and billing account but use different credentials.

---

## 1. DNS

| Type | Name   | Value            | TTL |
| ---- | ------ | ---------------- | --- |
| A    | `lang` | your server's IP | 300 |

```bash
dig +short lang.wharveytech.com
```

## 2. Get the code onto the server

```bash
git clone https://github.com/<you>/Language_App.git /home/deploy/parlo
```

```bash
cd /home/deploy/parlo && cp .env.example .env && nano .env
```

Set at least:

```dotenv
DOMAIN=lang.wharveytech.com
APP_SECRET=<openssl rand -hex 32>
POSTGRES_PASSWORD=<openssl rand -hex 24>
LLM_API_KEY=AIza...
TTS_API_KEY=AIza...
```

(`STT_API_KEY` defaults to `LLM_API_KEY` when both are Gemini.) If you use a service account for
Text-to-Speech instead of a key, put the JSON in `./secrets/google-tts.json` and set
`GOOGLE_APPLICATION_CREDENTIALS=/secrets/google-tts.json`.

## 3. Build and start

```bash
docker compose up -d --build
```

The API runs the migrations and seeds the curriculum on start. Check everything is healthy:

```bash
docker compose ps && curl -s http://127.0.0.1:7892/healthz
```

## 4. Nginx and HTTPS

```bash
sudo cp nginx.conf /etc/nginx/sites-available/parlo && sudo ln -s /etc/nginx/sites-available/parlo /etc/nginx/sites-enabled/
```

First pass: in `/etc/nginx/sites-available/parlo`, comment out the whole `listen 443` server block and the
`return 301` redirect, then:

```bash
sudo nginx -t && sudo systemctl reload nginx && sudo certbot --nginx -d lang.wharveytech.com
```

Second pass: uncomment what you commented out, then:

```bash
sudo nginx -t && sudo systemctl reload nginx
```

The WebSocket location in `nginx.conf` passes the `Upgrade` header and disables buffering for
conversations — without it replies arrive all at once (or not at all).

## 5. First login

Open `https://lang.wharveytech.com`, create the first account (it becomes the admin), then:

1. **Admin → Providers**: press each **Test** button (LLM, STT round-trip) and play a voice per
   language. Swap voices with **Compare voices** if you prefer another.
2. **Admin → Users**: create invite links for family or friends.
3. In AI Studio, confirm the Gemini project shows **Paid**; set a monthly budget alert in Google Cloud
   billing.

## 6. Backups

```bash
crontab -e
```

```cron
15 3 * * * cd /home/deploy/parlo && ./scripts/backup.sh >> backups/backup.log 2>&1
```

Set `BACKUP_PASSPHRASE` in `.env` to encrypt the files, and copy `./backups` somewhere off the box.

## Updating

```bash
cd /home/deploy/parlo && git pull && docker compose up -d --build
```

Migrations run automatically. Lessons whose YAML skeleton changed are regenerated on their next visit.

## Resource use

Limits are set per service in `docker-compose.yml`: the whole stack is capped at roughly 3.5 GB RAM and
idles well under 2 GB with cloud AI, and no single container can take more than 1.5 CPUs. The optional
`--profile local-ai` services add up to 4 GB and are not recommended on this box.
