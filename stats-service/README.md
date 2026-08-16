# PlaylistMuse stats aggregator

A tiny Cloudflare Worker that counts opt-in, anonymous "a playlist was generated"
pings from self-hosted PlaylistMuse installations, and exposes the total as a
shields.io badge. See `../README.md` for the badge and `backend/telemetry.py` for
what each installation actually sends (nothing identifying, ever).

## Deploy (one-time, ~5 minutes, free tier)

1. Create a free account at <https://dash.cloudflare.com/sign-up> if you don't have one.
2. Install Wrangler (Cloudflare's CLI) and log in:
   ```bash
   npm install -g wrangler
   wrangler login
   ```
3. From this directory, create the KV namespace that stores the counter:
   ```bash
   wrangler kv namespace create STATS_KV
   ```
   This prints an `id`. Paste it into `wrangler.toml` in place of
   `REPLACE_WITH_YOUR_KV_NAMESPACE_ID`.
4. Deploy:
   ```bash
   wrangler deploy
   ```
   Wrangler prints the public URL, something like
   `https://playlistmuse-stats.<your-account>.workers.dev`.

## After deploying

Give that URL to whoever maintains the PlaylistMuse backend deployment (or set it
yourself) as the `PLAYLISTMUSE_TELEMETRY_URL` environment variable, e.g.:

```bash
PLAYLISTMUSE_TELEMETRY_URL=https://playlistmuse-stats.<your-account>.workers.dev/ping
```

and update the badge URL in the main `README.md` to point at
`https://<your-account>.../badge.json`.

## Verifying it works

```bash
curl -i -X POST https://<your-worker-url>/ping -H "User-Agent: PlaylistMuse/0.2.2"
curl https://<your-worker-url>/badge.json
```

The second command should show the counter incrementing.
