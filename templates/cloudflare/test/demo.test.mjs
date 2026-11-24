import { test } from "node:test";
import assert from "node:assert/strict";
import { handle } from "../src/relay.js";
import { canonical } from "../src/demo.js";

const HOST = "elci.arda.workers.dev";
const NOW = Date.parse("2026-11-24T08:00:00Z");

async function demoEnv() {
  const pair = await crypto.subtle.generateKey({ name: "Ed25519" }, true, ["sign", "verify"]);
  const jwk = await crypto.subtle.exportKey("jwk", pair.privateKey);
  const demo = {
    id: `https://${HOST}/agents/demo`, endpoint: `https://${HOST}/inbox/demo`, domain: HOST,
    topics: ["demo", "scheduling"], delegation: "a.b.c", jwk: { kty: "OKP", crv: "Ed25519", x: jwk.x, d: jwk.d },
  };
  return { env: { ELCI_TOKEN: "t", ELCI_DEMO: JSON.stringify(demo) }, publicKey: pair.publicKey, demo };
}

// The demo must never touch storage.
const noStorage = new Proxy({}, { get: () => () => { throw new Error("storage used"); } });

const message = (over = {}) => ({
  protocol_version: "0.0.2", from: "https://them.example/agents/bot", to: `https://${HOST}/agents/demo`,
  on_behalf_of: "them.example", topic: "scheduling", intent: "query", thread: "thr_abcdef12",
  created_at: "2026-11-24T07:59:00Z", body: {}, delegation: "x.y.z", signature: "sig", ...over,
});

const post = (body, ip = "1.2.3.4") => new Request(`https://${HOST}/inbox/demo`, {
  method: "POST", headers: { "cf-connecting-ip": ip }, body: typeof body === "string" ? body : JSON.stringify(body),
});

const fromB64u = (s) => Uint8Array.from(atob(s.replace(/-/g, "+").replace(/_/g, "/")), (c) => c.charCodeAt(0));

test("demo answers a query at once with a signed reply and stores nothing", async () => {
  const { env, publicKey, demo } = await demoEnv();
  const r = await handle(post(message()), env, noStorage, NOW);
  assert.equal(r.status, 202);
  const { status, reply } = await r.json();
  assert.equal(status, "accepted");
  assert.equal(reply.from, demo.id);
  assert.equal(reply.to, "https://them.example/agents/bot");
  assert.equal(reply.thread, "thr_abcdef12");
  assert.equal(reply.intent, "answer");
  assert.equal(reply.created_at, "2026-11-24T08:00:00Z");
  assert.equal(reply.body.demo, true);
  assert.equal(reply.body.free.length, 3);
  const { signature, ...unsigned } = reply;
  const ok = await crypto.subtle.verify({ name: "Ed25519" }, publicKey, fromB64u(signature),
    new TextEncoder().encode(canonical(unsigned)));
  assert.ok(ok);
});

test("demo never accepts: a proposal or an accept goes to needs_human", async () => {
  const { env } = await demoEnv();
  for (const intent of ["propose", "accept"]) {
    const body = intent === "propose" ? { slots: ["2026-11-26T10:00:00Z/PT30M"] } : {};
    const { reply } = await (await handle(post(message({ intent, body }), `ip-${intent}`), env, noStorage, NOW)).json();
    assert.equal(reply.intent, "needs_human");
  }
});

test("demo rejects wrong topics, bad senders and floods", async () => {
  const { env } = await demoEnv();
  assert.equal((await handle(post(message({ topic: "payments" }), "a"), env, noStorage, NOW)).status, 400);
  assert.equal((await handle(post(message({ from: "http://x" }), "b"), env, noStorage, NOW)).status, 400);
  assert.equal((await handle(post("not json", "c"), env, noStorage, NOW)).status, 400);
  assert.equal((await handle(post("x".repeat(17 * 1024), "d"), env, noStorage, NOW)).status, 413);
  let last;
  for (let i = 0; i < 21; i++) last = await handle(post(message(), "flood"), env, noStorage, NOW);
  assert.equal(last.status, 429);
});

test("a broken ELCI_DEMO secret leaves the normal inbox working", async () => {
  const box = { getCard: async () => null };
  const r = await handle(post(message()), { ELCI_TOKEN: "t", ELCI_DEMO: "{oops" }, box, NOW);
  assert.equal(r.status, 404); // no card published: the ordinary path ran
});

test("canonical JSON sorts keys and refuses floats", () => {
  assert.equal(canonical({ b: 1, a: ["é", { d: null, c: true }] }), '{"a":["é",{"c":true,"d":null}],"b":1}');
  assert.throws(() => canonical({ a: 1.5 }));
});
