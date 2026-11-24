import { test } from "node:test";
import assert from "node:assert/strict";
import { handle } from "../src/relay.js";

const HOST = "elci.arda.workers.dev";
const CARD = {
  protocol_version: "0.0.2",
  principal: { name: "Arda", domain: HOST, jwks: { keys: [{ kty: "OKP", crv: "Ed25519", x: "AA" }] } },
  agents: [{ id: `https://${HOST}/agents/assistant`, topics: ["scheduling"], endpoint: `https://${HOST}/inbox/assistant`,
             jwks: { keys: [{ kty: "OKP", crv: "Ed25519", x: "AA" }] } }],
};
const ENV = { ELCI_TOKEN: "s3cret-token" };
const auth = { authorization: "Bearer s3cret-token" };

function memoryBox() {
  const rows = [];
  let card = null;
  return {
    rows,
    getCard: async () => card,
    putCard: async (t) => { card = t; },
    count: async () => rows.length,
    enqueue: async (i) => { rows.push(i); },
    list: async (n) => rows.slice(0, n),
    ack: async (ids) => { let d = 0; for (const id of ids) { const k = rows.findIndex((r) => r.id === id); if (k >= 0) { rows.splice(k, 1); d++; } } return d; },
  };
}

const req = (method, path, { body, headers = {} } = {}) =>
  new Request(`https://${HOST}${path}`, { method, headers, body: body === undefined ? undefined : typeof body === "string" ? body : JSON.stringify(body) });

async function published() {
  const box = memoryBox();
  const r = await handle(req("PUT", "/admin/card", { body: CARD, headers: auth }), ENV, box);
  assert.equal(r.status, 200);
  return box;
}

test("card is 404 until published, then served with caching", async () => {
  const box = memoryBox();
  assert.equal((await handle(req("GET", "/.well-known/elci.json"), ENV, box)).status, 404);
  await handle(req("PUT", "/admin/card", { body: CARD, headers: auth }), ENV, box);
  const r = await handle(req("GET", "/.well-known/elci.json"), ENV, box);
  assert.equal(r.status, 200);
  assert.equal(r.headers.get("cache-control"), "public, max-age=300");
  assert.deepEqual(await r.json(), CARD);
});

test("admin needs the token, and a token must be configured", async () => {
  const box = memoryBox();
  assert.equal((await handle(req("PUT", "/admin/card", { body: CARD }), ENV, box)).status, 401);
  assert.equal((await handle(req("PUT", "/admin/card", { body: CARD, headers: { authorization: "Bearer s3cret-tokeX" } }), ENV, box)).status, 401);
  assert.equal((await handle(req("GET", "/admin/messages", { headers: auth }), {}, box)).status, 503);
});

test("a card for another domain is refused", async () => {
  const other = { ...CARD, principal: { ...CARD.principal, domain: "evil.example" } };
  const r = await handle(req("PUT", "/admin/card", { body: other, headers: auth }), ENV, memoryBox());
  assert.equal(r.status, 400);
});

test("messages for a listed agent are queued, pulled and acked", async () => {
  const box = await published();
  const msg = { to: CARD.agents[0].id, intent: "propose", body: { slots: ["Thu 11:00"] } };
  const r = await handle(req("POST", "/inbox/assistant", { body: msg }), ENV, box, 1795000000000);
  assert.equal(r.status, 202);
  const list = await (await handle(req("GET", "/admin/messages", { headers: auth }), ENV, box)).json();
  assert.equal(list.length, 1);
  assert.deepEqual(list[0].message, msg);
  assert.equal(list[0].received_at, 1795000000000);
  const ack = await (await handle(req("POST", "/admin/ack", { body: { ids: [list[0].id] }, headers: auth }), ENV, box)).json();
  assert.equal(ack.deleted, 1);
  assert.equal(box.rows.length, 0);
});

test("unknown agents, wrong recipients, junk and oversized bodies are rejected", async () => {
  const box = await published();
  assert.equal((await handle(req("POST", "/inbox/nobody", { body: { to: "x" } }), ENV, box)).status, 404);
  assert.equal((await handle(req("POST", "/inbox/assistant", { body: { to: "https://elsewhere/a" } }), ENV, box)).status, 400);
  assert.equal((await handle(req("POST", "/inbox/assistant", { body: "not json" }), ENV, box)).status, 400);
  assert.equal((await handle(req("POST", "/inbox/assistant", { body: [1, 2] }), ENV, box)).status, 400);
  const big = { to: CARD.agents[0].id, pad: "x".repeat(300 * 1024) };
  assert.equal((await handle(req("POST", "/inbox/assistant", { body: big }), ENV, box)).status, 413);
  assert.equal(box.rows.length, 0);
});

test("the queue is capped", async () => {
  const box = await published();
  for (let i = 0; i < 1000; i++) box.rows.push({ id: `q${i}`, received_at: i, body: "{}" });
  const r = await handle(req("POST", "/inbox/assistant", { body: { to: CARD.agents[0].id } }), ENV, box);
  assert.equal(r.status, 503);
});
