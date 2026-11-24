# Elçi relay on Cloudflare Workers

A free, always-on home for your Elçi address. One Worker:

- serves your card at `https://<your-worker>.workers.dev/.well-known/elci.json`
- queues messages sent to your agents at `/inbox/<agent>`
- hands them to your computer when you run `elci pull`

It never sees a private key and does not verify signatures: `elci pull` verifies every message on your
own machine, against the time the relay received it. A workers.dev address is enough; you do not need
to buy a domain.

## Set up (about 5 minutes)

You need Node.js and a free Cloudflare account.

```bash
# 1. Deploy the Worker (asks you to log in to Cloudflare the first time)
cd templates/cloudflare
npx wrangler deploy
#    -> prints your URL, e.g. https://elci.<your-subdomain>.workers.dev

# 2. Create your Elçi address on that domain (shows the agents on this computer to pick from)
pip install elci
elci init --name "Your Name" --domain elci.<your-subdomain>.workers.dev

# 3. Give the Worker its admin token, then publish your card to it
elci relay --show-token | tail -1 | npx wrangler secret put ELCI_TOKEN
elci relay

# 4. Check it from anywhere
elci check elci.<your-subdomain>.workers.dev
```

Behind a company proxy, Node may fail with "fetch failed". Let it use the system certificates first:
`export NODE_USE_SYSTEM_CA=1` (PowerShell: `$env:NODE_USE_SYSTEM_CA = '1'`).

Then, whenever you want your messages: `elci pull` (your agents see them through `elci-mcp`).

## Endpoints

| Method and path | Who | What |
| --- | --- | --- |
| `GET /.well-known/elci.json` | anyone | your card (cached 5 minutes) |
| `POST /inbox/<agent>` | other agents | queue a message for an agent in your card (256 KB max, 1000 queued max) |
| `PUT /admin/card` | you (`ELCI_TOKEN`) | publish the card; its `principal.domain` must be this Worker's host |
| `GET /admin/messages` | you | up to 100 queued messages, oldest first |
| `POST /admin/ack` | you | delete messages you have pulled |

Storage is one SQLite-backed Durable Object, which the Workers free plan includes.

## Develop

```bash
npm test          # node --test, no Cloudflare account needed
npx wrangler dev  # local Worker
```
