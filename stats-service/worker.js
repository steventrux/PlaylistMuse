/**
 * Public aggregate counter for "playlists generated" across all opted-in,
 * self-hosted PlaylistMuse installations. Deployed as a Cloudflare Worker.
 *
 * POST /ping        Increment the counter by one. No body, no auth, no identifying
 *                    data is read or stored -- just a total count in KV. A short
 *                    per-IP rate limit (also in KV, TTL-based) exists only to blunt
 *                    trivial accidental/deliberate spam; this is a vanity counter,
 *                    not a security boundary.
 * GET  /badge.json   Current count, formatted for shields.io's "endpoint" badge type:
 *                    https://shields.io/badges/endpoint-badge
 *
 * KV binding expected: STATS_KV (see wrangler.toml).
 */

const COUNTER_KEY = "playlists_generated_total";
const RATE_LIMIT_WINDOW_SECONDS = 10;
const USER_AGENT_PREFIX = "PlaylistMuse/";
const BADGE_COLOR = "8B5CF6";

function badgeJson(count) {
  return {
    schemaVersion: 1,
    label: "playlists generated",
    message: Number(count).toLocaleString("en-US"),
    color: BADGE_COLOR,
  };
}

async function handlePing(request, env) {
  const userAgent = request.headers.get("User-Agent") || "";
  if (!userAgent.startsWith(USER_AGENT_PREFIX)) {
    return new Response(null, { status: 400 });
  }

  const clientIp = request.headers.get("CF-Connecting-IP") || "unknown";
  const rateLimitKey = `ratelimit:${clientIp}`;
  const alreadySeen = await env.STATS_KV.get(rateLimitKey);
  if (alreadySeen) {
    // Silently accept: the caller doesn't need to know it was throttled.
    return new Response(null, { status: 204 });
  }
  await env.STATS_KV.put(rateLimitKey, "1", { expirationTtl: RATE_LIMIT_WINDOW_SECONDS });

  const current = Number((await env.STATS_KV.get(COUNTER_KEY)) || "0");
  await env.STATS_KV.put(COUNTER_KEY, String(current + 1));

  return new Response(null, { status: 204 });
}

async function handleBadge(env) {
  const current = Number((await env.STATS_KV.get(COUNTER_KEY)) || "0");
  return new Response(JSON.stringify(badgeJson(current)), {
    status: 200,
    headers: {
      "Content-Type": "application/json",
      "Cache-Control": "public, max-age=300",
    },
  });
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (request.method === "POST" && url.pathname === "/ping") {
      return handlePing(request, env);
    }
    if (request.method === "GET" && url.pathname === "/badge.json") {
      return handleBadge(env);
    }
    return new Response("Not found", { status: 404 });
  },
};
