// Runs the relay logic on plain Node with in-memory storage, for interop tests.
// Usage: node test/serve-local.mjs <port> <token>
import http from "node:http";
import { handle } from "../src/relay.js";

const [port, token] = process.argv.slice(2);
const rows = [];
let card = null;
const box = {
  getCard: async () => card,
  putCard: async (t) => { card = t; },
  count: async () => rows.length,
  enqueue: async (i) => { rows.push(i); },
  list: async (n) => rows.slice(0, n),
  ack: async (ids) => { let d = 0; for (const id of ids) { const k = rows.findIndex((r) => r.id === id); if (k >= 0) { rows.splice(k, 1); d++; } } return d; },
};

http.createServer(async (req, res) => {
  const chunks = [];
  for await (const c of req) chunks.push(c);
  const body = chunks.length ? Buffer.concat(chunks) : undefined;
  const request = new Request(`https://${req.headers.host.split(":")[0]}${req.url}`,
    { method: req.method, headers: req.headers, body: req.method === "GET" ? undefined : body });
  const response = await handle(request, { ELCI_TOKEN: token }, box);
  res.writeHead(response.status, Object.fromEntries(response.headers));
  res.end(Buffer.from(await response.arrayBuffer()));
}).listen(Number(port), "127.0.0.1", () => console.log("ready"));
