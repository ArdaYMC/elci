"""Elçi demo: one person, three agents, two counterparties.

Arda has:
  * Jarvy      – internal coordinator with the full calendar. NOT in the public card.
  * devbyarda  – public creator agent (collaboration).
  * acme-work  – public work agent for a fictional company, "Acme Elektronik" (scheduling).

A brand's agent proposes a collaboration to devbyarda over HTTP. devbyarda asks Jarvy for
availability and answers at the `busy_free` level only, so the brand never learns what the
busy slot is. Meanwhile acme-work reaches a supplier who has no agent, by email, and reads the
reply back. Every binding step waits for Arda's approval.

Run:  python examples/three_agents.py          (from the repo root, after `pip install -e python`)
"""

from __future__ import annotations

import time
from email.message import EmailMessage

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from elci import (
    Agent,
    AgentCard,
    Delegation,
    DisclosurePolicy,
    Inbox,
    compose_fallback_email,
    issue_approval,
    issue_delegation,
    parse_reply,
    public_jwk,
)
from elci.inbox import send, serve

# --- Jarvy: the only place the full calendar lives --------------------------------------------
CALENDAR = {
    "2026-11-26T14:00": {"busy": True, "title": "Acme – tedarikçi toplantısı", "attendees": ["supplier@example.com"]},
    "2026-11-27T11:00": {"busy": False},
}


def jarvy_availability(slot: str) -> dict:
    return {"slot": slot, **CALENDAR.get(slot, {"busy": False})}


# --- helpers ---------------------------------------------------------------------------------
def principal(domain: str, name: str, agents: dict[str, tuple[tuple[str, ...], tuple[str, ...]]], endpoint: str):
    pkey = Ed25519PrivateKey.generate()
    entries, handles = [], {}
    for agent_name, (topics, intents) in agents.items():
        akey = Ed25519PrivateKey.generate()
        agent_id = f"https://{domain}/agents/{agent_name}"
        entries.append({"id": agent_id, "name": agent_name, "topics": list(topics),
                        "endpoint": endpoint, "jwks": {"keys": [public_jwk(akey.public_key())]}})
        token = issue_delegation(Delegation(domain, agent_id, topics, intents, int(time.time()) + 3600), pkey)
        handles[agent_name] = Agent(agent_id, domain, akey, token)
    card = AgentCard.from_dict({
        "protocol_version": "0.0.2",
        "principal": {"name": name, "domain": domain, "fallback": f"mailto:hello@{domain}",
                      "jwks": {"keys": [public_jwk(pkey.public_key())]}},
        "agents": entries,
    })
    return card, handles, pkey


def approve(principal_key, what: str, auto_yes: bool, *, thread: str, intent: str, body: dict) -> dict:
    """Ask the human. In the demo the answer is 'yes' when auto_yes is set."""
    print(f"   [ONAY / APPROVAL] Arda'ya soruluyor: {what}")
    if not auto_yes and input("   Onaylıyor musun? (e/h) ").strip().lower() not in {"e", "evet", "y", "yes"}:
        raise SystemExit("Arda onaylamadı, işlem durdu.")
    receipt = issue_approval(principal_key, principal="arda.example", thread=thread, intent=intent, body=body,
                             summary=what)
    print("   [ONAY] verildi, imzalı makbuz eklendi")
    return receipt


def main(auto_yes: bool = True) -> dict:
    log: dict = {}
    # Servers first, so cards can carry their endpoints.
    cards: dict[str, AgentCard] = {}
    arda_handlers, brand_inbox_msgs = {}, []

    def arda_handle(message):
        return arda_handlers[message["to"]](message)

    def brand_handle(message):
        brand_inbox_msgs.append(message)
        return None

    # Bind servers on free ports; the inbox is built once the cards exist.
    class LazyInbox:
        def __init__(self, domain):
            self.domain = domain
            self.inner = None

        def accept(self, message):
            if self.inner is None:
                self.inner = Inbox(cards[self.domain], resolve_card=cards.__getitem__)
            return self.inner.accept(message)

    arda_srv = serve(LazyInbox("arda.example"), arda_handle)
    brand_srv = serve(LazyInbox("brand.example"), brand_handle)
    arda_url = f"http://127.0.0.1:{arda_srv.server_address[1]}/"
    brand_url = f"http://127.0.0.1:{brand_srv.server_address[1]}/"
    try:
        # Card endpoints must be https; the demo maps them to the local servers.
        arda_card, arda, arda_pkey = principal("arda.example", "Arda", {
            "devbyarda": (("collaboration",), ("answer", "accept")),
            "acme-work": (("scheduling",), ("propose", "query")),
        }, "https://arda.example/elci")
        brand_card, brand, _ = principal("brand.example", "Brand Co.", {
            "partnerships": (("collaboration",), ("propose",)),
        }, "https://brand.example/elci")
        cards.update({"arda.example": arda_card, "brand.example": brand_card})
        local = {"arda.example": arda_url, "brand.example": brand_url}

        policy = DisclosurePolicy(allowed={"availability": "busy_free"})

        def devbyarda_on_message(message):
            slots = message["body"]["slots"]
            print(f"2) devbyarda teklifi aldı, Jarvy'ye müsaitlik soruyor: {slots}")
            full = [jarvy_availability(s) for s in slots]
            shared = [policy.redact(r) for r in full]
            print(f"3) Jarvy tam kaydı verdi; devbyarda yalnızca şunu paylaşıyor: {shared}")
            free = [r["slot"] for r in shared if not r["busy"]]
            answer = arda["devbyarda"].message(to=message["from"], topic="collaboration", intent="answer",
                                                body={"availability": shared}, thread=message["thread"])
            send(answer, local["brand.example"], allow_insecure_localhost=True)
            log["answer"] = answer
            if free:
                body = {"slot": free[0]}
                receipt = approve(arda_pkey, f"Brand Co. ile iş birliği, {free[0]}", auto_yes,
                                  thread=message["thread"], intent="accept", body=body)
                accept = arda["devbyarda"].message(to=message["from"], topic="collaboration", intent="accept",
                                                    body=body, thread=message["thread"], approval=receipt)
                send(accept, local["brand.example"], allow_insecure_localhost=True)
                log["accept"] = accept
            return {"received": True}

        arda_handlers[arda["devbyarda"].id] = devbyarda_on_message

        print("1) Marka ajanı devbyarda'ya iş birliği teklif ediyor (HTTP, imzalı, yetki belgeli)")
        proposal = brand["partnerships"].message(
            to=arda["devbyarda"].id, topic="collaboration", intent="propose",
            body={"slots": list(CALENDAR), "note": "Reels iş birliği"})
        status, _ = send(proposal, local["arda.example"], allow_insecure_localhost=True)
        print(f"   teslim durumu: {status}")
        print(f"4) Marka tarafına ulaşan mesajlar: {[m['intent'] for m in brand_inbox_msgs]}")
        log["brand_saw"] = brand_inbox_msgs

        print("\n5) acme-work, ajanı olmayan tedarikçiye e-postayla ulaşıyor")
        ask = arda["acme-work"].message(to="mailto:supplier@example.com", topic="scheduling", intent="propose",
                                         body={"slots": ["2026-12-01 10:00", "2026-12-02 15:00"],
                                               "note": "Aralık siparişi için kısa bir görüşme"})
        email = compose_fallback_email(ask, from_addr="assistant@arda.example", to_addr="supplier@example.com",
                                       sender_name="Acme Elektronik")
        print("   --- giden e-posta ---")
        print("   " + email.get_content().replace("\n", "\n   "))
        reply = EmailMessage()
        reply["From"], reply["To"], reply["Subject"] = "supplier@example.com", "assistant@arda.example", "Re: x"
        reply.set_content("2, uygun.\n\n> elci-thread: " + ask["thread"])
        parsed = parse_reply(bytes(reply))
        print(f"6) Cevap ayrıştırıldı: seçenek={parsed.choice}, thread={parsed.thread}, onay gerekli={parsed.needs_confirmation}")
        chosen = ask["body"]["slots"][parsed.choice - 1]
        log["supplier_receipt"] = approve(arda_pkey, f"Tedarikçi görüşmesi {chosen}", auto_yes,
                                          thread=ask["thread"], intent="accept", body={"slot": chosen})
        log["supplier_slot"] = chosen
        print("7) Jarvy takvime işledi. Bitti.")
        return log
    finally:
        arda_srv.shutdown()
        brand_srv.shutdown()


if __name__ == "__main__":
    import sys

    main(auto_yes="--yes" in sys.argv)
