"""Email fallback: reach a person who has no agent, and read their answer back.

Composing is deterministic; parsing a human reply is best effort. Per spec section 6, a parsed
reply is never binding on its own: ``FallbackReply.needs_confirmation`` is always True.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from email import message_from_bytes, policy
from email.message import EmailMessage

THREAD_HEADER = "X-Elci-Thread"
_FOOTER_RE = re.compile(r"elci-thread:\s*([A-Za-z0-9_-]{8,})")
_YES = {"yes", "ok", "okay", "sure", "evet", "tamam", "olur", "uygun"}
_NO = {"no", "decline", "hayır", "hayir", "olmaz", "uygun değil", "uygun degil"}


def compose_fallback_email(message: dict, *, from_addr: str, to_addr: str, sender_name: str) -> EmailMessage:
    """Turn a ``propose`` or ``query`` Elçi message into a plain email a human can answer."""
    body = message.get("body", {})
    options = body.get("slots") or body.get("options") or []
    lines = [f"Merhaba / Hello,", "", f"{sender_name} sizinle şu konuda iletişime geçmek istiyor / "
             f"would like to reach you about: {message['topic']}."]
    if body.get("note"):
        lines += ["", str(body["note"])]
    if options:
        lines += ["", "Seçenekler / Options:"]
        lines += [f"  {i}. {opt}" for i, opt in enumerate(options, start=1)]
        lines += ["", "Uygun olanın numarasıyla cevap verin, ya da \"hayır\" yazın. / "
                      "Reply with the number that suits you, or \"no\"."]
    lines += ["", "--", f"Bu e-postayı {sender_name} adına bir asistan gönderdi; cevabınızı {sender_name} onaylayacak.",
              f"Sent by an assistant on behalf of {sender_name}; {sender_name} confirms every answer.",
              f"elci-thread: {message['thread']}"]
    email = EmailMessage()
    email["From"] = from_addr
    email["To"] = to_addr
    email["Subject"] = f"[{sender_name}] {message['topic']}"
    email[THREAD_HEADER] = message["thread"]
    email.set_content("\n".join(lines))
    return email


@dataclass(frozen=True)
class FallbackReply:
    thread: str | None
    choice: int | None  # 1-based option number the person picked
    declined: bool
    accepted: bool
    text: str  # the person's own words, quoted history removed
    needs_confirmation: bool = True


def _own_words(text: str) -> str:
    kept = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(">"):
            continue
        if re.match(r"^(On .+ wrote:|.+ tarihinde .+ yazdı:)$", stripped):
            break
        if stripped == "--":
            break
        kept.append(line)
    return "\n".join(kept).strip()


def parse_reply(raw: bytes) -> FallbackReply:
    """Best-effort reading of a human reply to a fallback email."""
    msg = message_from_bytes(raw, policy=policy.default)
    part = msg.get_body(preferencelist=("plain",))
    full = part.get_content() if part else ""
    thread = msg.get(THREAD_HEADER)
    if not thread:
        found = _FOOTER_RE.search(full)
        thread = found.group(1) if found else None
    words = _own_words(full)
    first = words.splitlines()[0].strip().lower() if words else ""
    choice = None
    m = re.match(r"^\(?(\d{1,2})\)?[.,)]?(\s|$)", first)
    if m:
        choice = int(m.group(1))
    cleaned = first.strip(" .!")
    declined = cleaned in _NO or cleaned.startswith(("hayır", "hayir", "no ", "no,"))
    accepted = choice is not None or cleaned in _YES
    return FallbackReply(thread, choice, declined, accepted and not declined, words)
