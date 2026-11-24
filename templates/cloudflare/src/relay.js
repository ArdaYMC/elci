// Elçi relay: serves your card and queues incoming messages until `elci pull` fetches them.
// It does not verify signatures: your own machine does that on pull, with the Python package.
// Pure request handling lives here so it can be tested without Cloudflare (see test/).

const MAX_MESSAGE = 256 * 1024;
const MAX_CARD = 64 * 1024;
const MAX_QUEUE = 1000;
const PAGE = 100;

const json = (status, body, extra = {}) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json; charset=utf-8", ...extra },
  });

async function readLimited(request, limit) {
  const declared = Number(request.headers.get("content-length") || "0");
  if (declared > limit) return null;
  const text = await request.text();
  return new TextEncoder().encode(text).length > limit ? null : text;
}

function authorized(request, env) {
  const expected = `Bearer ${env.ELCI_TOKEN || ""}`;
  const given = request.headers.get("authorization") || "";
  if (!env.ELCI_TOKEN || given.length !== expected.length) return false;
  let diff = 0;
  for (let i = 0; i < expected.length; i++) diff |= expected.charCodeAt(i) ^ given.charCodeAt(i);
  return diff === 0;
}

function parseObject(text) {
  try {
    const value = JSON.parse(text);
    return value && typeof value === "object" && !Array.isArray(value) ? value : null;
  } catch {
    return null;
  }
}

export async function handle(request, env, box, now = Date.now()) {
  const url = new URL(request.url);
  const path = url.pathname;

  if (request.method === "GET" && path === "/.well-known/elci.json") {
    const card = await box.getCard();
    if (!card) return json(404, { error: "no card published yet: run `elci relay`" });
    return new Response(card, {
      headers: {
        "content-type": "application/json; charset=utf-8",
        "cache-control": "public, max-age=300",
        "access-control-allow-origin": "*",
      },
    });
  }

  if (request.method === "POST" && path.startsWith("/inbox/")) {
    const cardText = await box.getCard();
    const card = cardText ? JSON.parse(cardText) : null;
    const agent = card?.agents?.find((a) => new URL(a.endpoint).pathname === path);
    if (!agent) return json(404, { status: "rejected", reason: "no such agent here" });
    const text = await readLimited(request, MAX_MESSAGE);
    if (text === null) return json(413, { status: "rejected", reason: "message too large" });
    const message = parseObject(text);
    if (!message || message.to !== agent.id) {
      return json(400, { status: "rejected", reason: "not an Elçi message for this agent" });
    }
    if ((await box.count()) >= MAX_QUEUE) {
      return json(503, { status: "rejected", reason: "inbox full, try later" }, { "retry-after": "3600" });
    }
    const id = `q_${now}_${crypto.randomUUID().slice(0, 8)}`;
    await box.enqueue({ id, received_at: now, body: text });
    return json(202, { status: "queued", id });
  }

  if (path.startsWith("/admin/")) {
    if (!env.ELCI_TOKEN) return json(503, { error: "set the ELCI_TOKEN secret first" });
    if (!authorized(request, env)) return json(401, { error: "unauthorized" });

    if (request.method === "PUT" && path === "/admin/card") {
      const text = await readLimited(request, MAX_CARD);
      const card = text && parseObject(text);
      if (!card) return json(400, { error: "card must be a JSON object under 64 KB" });
      if (card.principal?.domain?.toLowerCase() !== url.hostname.toLowerCase()) {
        return json(400, { error: `card is for ${card.principal?.domain}, this relay is ${url.hostname}` });
      }
      await box.putCard(JSON.stringify(card, null, 2));
      return json(200, { status: "published" });
    }
    if (request.method === "GET" && path === "/admin/messages") {
      const rows = await box.list(PAGE);
      return json(200, rows.map((r) => ({ id: r.id, received_at: r.received_at, message: JSON.parse(r.body) })));
    }
    if (request.method === "POST" && path === "/admin/ack") {
      const body = parseObject((await readLimited(request, MAX_MESSAGE)) || "");
      const ids = Array.isArray(body?.ids) ? body.ids.filter((i) => typeof i === "string").slice(0, PAGE) : [];
      return json(200, { deleted: await box.ack(ids) });
    }
  }

  if (request.method === "GET" && path === "/") {
    return new Response("Elçi relay. Card: /.well-known/elci.json\n", { headers: { "content-type": "text/plain" } });
  }
  return json(404, { error: "not found" });
}
