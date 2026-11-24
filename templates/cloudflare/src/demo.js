// Public demo agent: answers on the spot with a signed Elçi message, so anyone can try Elçi.
//
// It runs inside the Worker, touches no storage and no other machine, and only ever returns fixed
// sample data. It holds one key: the demo agent's own (never the principal key), with a delegation
// that does not include `accept`. If that key leaks, revoke the delegation with `elci revoke`.
//
// Configure with one secret, ELCI_DEMO, printed by `elci export-agent <name>`:
//   {"id": "...", "endpoint": "...", "domain": "...", "topics": [...], "delegation": "...", "jwk": {"kty":"OKP","crv":"Ed25519","x":"...","d":"..."}}

const INTENTS = new Set(["propose", "query", "answer", "accept", "decline", "needs_human"]);
const MAX_DEMO_MESSAGE = 16 * 1024;
const RATE = 20; // requests per minute per client address
const NOTE = "Sample data from the Elçi demo agent. Nothing here is a real calendar or a real commitment.";

export function canonical(value) {
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (value && typeof value === "object") {
    return `{${Object.keys(value).sort().map((k) => `${JSON.stringify(k)}:${canonical(value[k])}`).join(",")}}`;
  }
  if (typeof value === "number" && !Number.isInteger(value)) throw new TypeError("no floats in canonical JSON");
  return JSON.stringify(value);
}

const b64u = (bytes) =>
  btoa(String.fromCharCode(...new Uint8Array(bytes))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");

export function parseDemo(text) {
  if (!text) return null;
  const demo = JSON.parse(text);
  for (const k of ["id", "endpoint", "domain", "delegation"]) if (typeof demo[k] !== "string") throw new Error(`ELCI_DEMO.${k} missing`);
  if (!Array.isArray(demo.topics) || !demo.jwk?.d) throw new Error("ELCI_DEMO.topics or jwk missing");
  return { ...demo, path: new URL(demo.endpoint).pathname };
}

const keys = new Map();
async function signingKey(jwk) {
  if (!keys.has(jwk.x)) {
    keys.set(jwk.x, crypto.subtle.importKey("jwk", { kty: "OKP", crv: "Ed25519", x: jwk.x, d: jwk.d },
      { name: "Ed25519" }, false, ["sign"]));
  }
  return keys.get(jwk.x);
}

export async function sign(message, jwk) {
  const data = new TextEncoder().encode(canonical(message));
  const sig = await crypto.subtle.sign({ name: "Ed25519" }, await signingKey(jwk), data);
  return { ...message, signature: b64u(sig) };
}

function sampleSlots(now) {
  const out = [];
  const day = new Date(now);
  while (out.length < 3) {
    day.setUTCDate(day.getUTCDate() + 1);
    const wd = day.getUTCDay();
    if (wd === 0 || wd === 6) continue;
    const d = day.toISOString().slice(0, 10);
    out.push(`${d}T${["09", "13", "15"][out.length]}:00:00Z/PT30M`);
  }
  return out;
}

function answerFor(message, now) {
  const slots = sampleSlots(now);
  const offered = Array.isArray(message.body?.slots) ? message.body.slots.filter((s) => typeof s === "string") : [];
  switch (message.intent) {
    case "query":
      return ["answer", { text: "Hi, I am the Elçi demo agent. These sample slots are free.", free: slots }];
    case "propose":
      if (offered.length) {
        return ["needs_human", {
          text: `${offered[0].slice(0, 64)} could work. A real agent would now ask its human to approve; ` +
            "this demo never commits to anything.",
          picked: offered[0].slice(0, 64),
        }];
      }
      return ["propose", { text: "Here are some sample slots.", slots }];
    case "accept":
      return ["needs_human", { text: "A demo agent cannot be bound to anything." }];
    default:
      return ["answer", { text: "Noted. Thanks for trying Elçi." }];
  }
}

export async function demoReply(message, demo, now = Date.now()) {
  const [intent, body] = answerFor(message, now);
  const reply = {
    protocol_version: "0.0.2",
    from: demo.id,
    to: message.from,
    on_behalf_of: demo.domain,
    topic: message.topic,
    intent,
    thread: message.thread,
    created_at: new Date(now).toISOString().replace(/\.\d{3}Z$/, "Z"),
    body: { ...body, demo: true, note: NOTE },
    delegation: demo.delegation,
  };
  return sign(reply, demo.jwk);
}

// Returns a rejection reason, or null when the message is fine to answer.
export function checkDemoMessage(message, demo) {
  if (!message || message.to !== demo.id) return "not an Elçi message for this agent";
  if (typeof message.from !== "string" || !message.from.startsWith("https://") || message.from.length > 512) {
    return "from must be an https agent id";
  }
  if (!INTENTS.has(message.intent)) return "unknown intent";
  if (typeof message.thread !== "string" || message.thread.length < 8 || message.thread.length > 128) {
    return "thread must be 8 to 128 characters";
  }
  if (!demo.topics.includes(message.topic)) return `topic not handled here; try one of: ${demo.topics.join(", ")}`;
  if (!message.body || typeof message.body !== "object" || Array.isArray(message.body)) return "body must be an object";
  return null;
}

// Per-isolate sliding window. Not global, but enough to keep one client from burning the free quota.
const hits = new Map();
export function allow(client, now = Date.now()) {
  const recent = (hits.get(client) || []).filter((t) => now - t < 60_000);
  if (recent.length >= RATE) return false;
  recent.push(now);
  hits.set(client, recent);
  if (hits.size > 10_000) hits.clear();
  return true;
}

export { MAX_DEMO_MESSAGE };
