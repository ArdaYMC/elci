import { DurableObject } from "cloudflare:workers";
import { handle } from "./relay.js";

// One Durable Object holds the card and the queue (SQLite storage, free plan friendly).
export class Mailbox extends DurableObject {
  constructor(ctx, env) {
    super(ctx, env);
    this.sql = ctx.storage.sql;
    this.sql.exec("CREATE TABLE IF NOT EXISTS messages (id TEXT PRIMARY KEY, received_at INTEGER, body TEXT)");
    this.sql.exec("CREATE TABLE IF NOT EXISTS settings (k TEXT PRIMARY KEY, v TEXT)");
  }
  async getCard() {
    const rows = this.sql.exec("SELECT v FROM settings WHERE k = 'card'").toArray();
    return rows.length ? rows[0].v : null;
  }
  async putCard(text) {
    this.sql.exec("INSERT OR REPLACE INTO settings (k, v) VALUES ('card', ?)", text);
  }
  async count() {
    return this.sql.exec("SELECT COUNT(*) AS n FROM messages").one().n;
  }
  async enqueue(item) {
    this.sql.exec("INSERT INTO messages (id, received_at, body) VALUES (?, ?, ?)", item.id, item.received_at, item.body);
  }
  async list(limit) {
    return this.sql.exec("SELECT id, received_at, body FROM messages ORDER BY received_at LIMIT ?", limit).toArray();
  }
  async ack(ids) {
    let deleted = 0;
    for (const id of ids) deleted += this.sql.exec("DELETE FROM messages WHERE id = ?", id).rowsWritten;
    return deleted;
  }
}

export default {
  async fetch(request, env) {
    const box = env.MAILBOX.get(env.MAILBOX.idFromName("mailbox"));
    return handle(request, env, box);
  },
};
