from email.message import EmailMessage

from elci.fallback import THREAD_HEADER, compose_fallback_email, parse_reply

MSG = {
    "topic": "scheduling",
    "intent": "propose",
    "thread": "thr_acme0001",
    "body": {"slots": ["2026-11-27 10:00", "2026-11-28 15:00"], "note": "Sipariş görüşmesi"},
}


def _reply(text: str, with_header: bool = False) -> bytes:
    e = EmailMessage()
    e["From"] = "supplier@example.com"
    e["To"] = "agent@acme.example"
    e["Subject"] = "Re: [Acme] scheduling"
    if with_header:
        e[THREAD_HEADER] = "thr_acme0001"
    e.set_content(text)
    return bytes(e)


def test_compose_lists_options_and_thread():
    email = compose_fallback_email(MSG, from_addr="agent@acme.example", to_addr="supplier@example.com",
                                   sender_name="Acme")
    body = email.get_content()
    assert "1. 2026-11-27 10:00" in body and "2. 2026-11-28 15:00" in body
    assert "elci-thread: thr_acme0001" in body
    assert email[THREAD_HEADER] == "thr_acme0001"


def test_reply_with_number_and_quoted_footer():
    original = compose_fallback_email(MSG, from_addr="a@acme.example", to_addr="s@example.com", sender_name="Acme")
    quoted = "\n".join("> " + line for line in original.get_content().splitlines())
    r = parse_reply(_reply(f"2, görüşürüz\n\nOn Mon, Acme wrote:\n{quoted}"))
    assert r.thread is None or r.thread == "thr_acme0001"
    assert r.choice == 2 and r.accepted and not r.declined
    assert r.needs_confirmation


def test_thread_from_footer_in_body():
    r = parse_reply(_reply("Evet uygun\n\nelci-thread: thr_acme0001"))
    assert r.thread == "thr_acme0001"


def test_thread_from_header_and_decline():
    r = parse_reply(_reply("Hayır, bu hafta olmaz.", with_header=True))
    assert r.thread == "thr_acme0001" and r.declined and not r.accepted


def test_unclear_reply_is_neither():
    r = parse_reply(_reply("Bir sonraki hafta arayabilir misiniz?", with_header=True))
    assert r.choice is None and not r.accepted and not r.declined
    assert "sonraki hafta" in r.text


def test_reply_with_option_or_ordinal_phrases():
    for sample, expected in [
        ("the second one works for me", 2),
        ("ikincisi uygun", 2),
        ("Option 1 please", 1),
    ]:
        r = parse_reply(_reply(sample, with_header=True))
        assert r.choice == expected and r.accepted and not r.declined
        assert r.needs_confirmation
