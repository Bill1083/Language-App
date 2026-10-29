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
git clone https://github.com/Bill1083/Language-App.git /home/deploy/parlo
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
conversations — without it replies arrive all at once (or not at all). It also repeats the `Host` and
`X-Forwarded-*` headers: a location with its own `proxy_set_header` lines inherits none of the server's,
and without `Host` the API can't match the browser's origin. Keep those lines if you edit the file by hand.

## 5. First login

Open `https://lang.wharveytech.com`, create the first account (it becomes the admin), then:

1. **Admin → Providers**: press each **Test** button (**Test conversation**, feedback, content, the STT
   round-trip) and play a voice per language. Swap voices with **Compare voices** if you prefer another.
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

If you changed `nginx.conf` in the repo, copy the changed lines into `/etc/nginx/sites-available/parlo`
(not the whole file — Certbot edited yours), then `sudo nginx -t && sudo systemctl reload nginx`.

## Troubleshooting conversations

- **"Can't connect" / "Connection refused"** — the WebSocket was rejected before it opened. Check the
  WebSocket location in `/etc/nginx/sites-available/parlo` has the four `proxy_set_header Host … /
  X-Real-IP / X-Forwarded-For / X-Forwarded-Proto` lines, and that `DOMAIN` in `.env` is the address
  you open in the browser. `docker compose logs api | grep -i origin` shows the origin it refused.
- **"The AI couldn't start the conversation"** — the connection is fine but the language model call
  failed; the box under the message shows the provider's error. Run **Admin → Providers → Test
  conversation**. Usual causes: the Gemini key is restricted to other APIs (allow the **Generative
  Language API**, or remove the restriction), or the project isn't on a paid tier (429 quota errors).
- **"Gemini error 503: This model is currently experiencing high demand"** — Google's side, and
  usually temporary. Parlo switches to the backup model (`LLM_MODEL_FALLBACK`, default
  `gemini-3.5-flash-lite`) when the main one is overloaded, hasn't started replying within 12 s
  or hasn't transcribed a recording within 12 s, and keeps using the backup first for five minutes. The admin test shows which model answered. If
  it keeps happening, set a different main model in **Admin → Providers**.

## Resource use

Limits are set per service in `docker-compose.yml`: the whole stack is capped at roughly 3.5 GB RAM and
idles well under 2 GB with cloud AI, and no single container can take more than 1.5 CPUs. The optional
`--profile local-ai` services add up to 4 GB and are not recommended on this box.
