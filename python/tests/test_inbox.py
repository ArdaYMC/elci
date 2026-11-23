import pytest

from elci import Inbox, Rejected
from elci.inbox import send, serve


def inbox_for(cards, domain):
    return Inbox(cards[domain], resolve_card=cards.__getitem__, fetch_keys=lambda uri: [])


def test_valid_message_is_accepted(pair):
    cards, creator, brand = pair
    msg = brand.message(to=creator.id, topic="collaboration", intent="propose", body={"slots": ["Fri 10:00"]})
    assert inbox_for(cards, "creator.example").accept(msg) == msg


def test_replay_is_rejected(pair):
    cards, creator, brand = pair
    inbox = inbox_for(cards, "creator.example")
    msg = brand.message(to=creator.id, topic="collaboration", intent="propose", body={})
    inbox.accept(msg)
    with pytest.raises(Rejected) as exc:
        inbox.accept(msg)
    assert exc.value.status == 409


@pytest.mark.parametrize("change, status", [
    ({"topic": "scheduling"}, 403),          # recipient does not take this topic
    ({"to": "https://creator.example/agents/nobody"}, 404),
    ({"body": {"slots": ["tampered"]}}, 401),  # breaks the signature
])
def test_bad_messages_are_rejected(pair, change, status):
    cards, creator, brand = pair
    msg = {**brand.message(to=creator.id, topic="collaboration", intent="propose", body={}), **change}
    with pytest.raises(Rejected) as exc:
        inbox_for(cards, "creator.example").accept(msg)
    assert exc.value.status == status


def test_intent_outside_delegation_is_rejected(pair):
    cards, creator, brand = pair
    msg = brand.message(to=creator.id, topic="collaboration", intent="decline", body={})
    with pytest.raises(Rejected, match="intent"):
        inbox_for(cards, "creator.example").accept(msg)


def test_impersonation_is_rejected(pair):
    cards, creator, brand = pair
    # brand's agent signs, but claims to be creator's agent
    msg = brand.message(to=creator.id, topic="collaboration", intent="propose", body={})
    forged = {**msg, "from": creator.id, "on_behalf_of": "creator.example"}
    with pytest.raises(Rejected):
        inbox_for(cards, "creator.example").accept(forged)


def test_http_round_trip(pair):
    cards, creator, brand = pair
    received = []
    server = serve(inbox_for(cards, "creator.example"), lambda m: received.append(m) or {"ok": True})
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}/"
        msg = brand.message(to=creator.id, topic="collaboration", intent="propose", body={"slots": ["Fri"]})
        status, reply = send(msg, url, allow_insecure_localhost=True)
        assert status == 202 and reply["reply"] == {"ok": True} and received == [msg]
        status, reply = send(msg, url, allow_insecure_localhost=True)
        assert status == 409
    finally:
        server.shutdown()


def test_send_refuses_plain_http():
    with pytest.raises(ValueError):
        send({}, "http://example.com/elci")


def _accept_pair():
    from conftest import make_principal
    a_card, a_agent, _ = make_principal("a.example", "x", ("collaboration",), ("propose",))
    b_card, b_agent, b_pkey = make_principal("b.example", "y", ("collaboration",), ("accept",))
    return {"a.example": a_card, "b.example": b_card}, a_agent, b_agent, b_pkey


def test_accept_without_approval_is_rejected():
    cards, a, b, _ = _accept_pair()
    msg = b.message(to=a.id, topic="collaboration", intent="accept", body={}, thread="thr_00000001")
    with pytest.raises(Rejected, match="approval"):
        inbox_for(cards, "a.example").accept(msg)


def test_accept_with_valid_approval_is_accepted():
    from elci import issue_approval
    cards, a, b, b_pkey = _accept_pair()
    receipt = issue_approval(b_pkey, principal="b.example", thread="thr_00000001", intent="accept", summary="ok")
    msg = b.message(to=a.id, topic="collaboration", intent="accept", body={}, thread="thr_00000001", approval=receipt)
    assert inbox_for(cards, "a.example").accept(msg)


def test_approval_for_another_thread_is_rejected():
    from elci import issue_approval
    cards, a, b, b_pkey = _accept_pair()
    receipt = issue_approval(b_pkey, principal="b.example", thread="thr_other0001", intent="accept", summary="ok")
    msg = b.message(to=a.id, topic="collaboration", intent="accept", body={}, thread="thr_00000001", approval=receipt)
    with pytest.raises(Rejected):
        inbox_for(cards, "a.example").accept(msg)


def test_approval_signed_by_agent_not_principal_is_rejected():
    from elci import issue_approval
    cards, a, b, _ = _accept_pair()
    receipt = issue_approval(b.key, principal="b.example", thread="thr_00000001", intent="accept", summary="ok")
    msg = b.message(to=a.id, topic="collaboration", intent="accept", body={}, thread="thr_00000001", approval=receipt)
    with pytest.raises(Rejected):
        inbox_for(cards, "a.example").accept(msg)
