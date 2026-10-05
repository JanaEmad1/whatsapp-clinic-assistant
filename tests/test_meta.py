import hashlib
import hmac
import json

from fastapi.testclient import TestClient

from clinic import api, config, handoff, meta_whatsapp

PATIENT, STAFF = "96560001111", "201000000000"


def _payload(text: str, sender: str = PATIENT, msg_id: str = "wamid.1") -> dict:
    return {"object": "whatsapp_business_account", "entry": [{"id": "1", "changes": [{"field": "messages", "value": {
        "messaging_product": "whatsapp",
        "contacts": [{"wa_id": sender, "profile": {"name": "Fatma"}}],
        "messages": [{"id": msg_id, "from": sender, "timestamp": "1", "type": "text", "text": {"body": text}}],
    }}]}]}


def _client(agent, monkeypatch, sent):
    monkeypatch.setattr(api, "get_agent", lambda: agent)
    monkeypatch.setattr(api, "get_engine", lambda: agent.engine)
    monkeypatch.setattr(meta_whatsapp, "send_message", lambda to, body: sent.append((to, body)))
    monkeypatch.setattr(config, "META_APP_SECRET", "")
    monkeypatch.setattr(api, "_seen_message_ids", set())
    return TestClient(api.app)


def test_verification_handshake(monkeypatch):
    monkeypatch.setattr(config, "META_VERIFY_TOKEN", "my-token")
    client = TestClient(api.app)
    ok = client.get("/meta", params={"hub.mode": "subscribe", "hub.verify_token": "my-token", "hub.challenge": "42"})
    assert ok.status_code == 200 and ok.text == "42"
    bad = client.get("/meta", params={"hub.mode": "subscribe", "hub.verify_token": "nope", "hub.challenge": "42"})
    assert bad.status_code == 403


def test_signature_check():
    body = b'{"a": 1}'
    good = "sha256=" + hmac.new(b"secret", body, hashlib.sha256).hexdigest()
    assert meta_whatsapp.signature_ok(body, good, "secret")
    assert not meta_whatsapp.signature_ok(body, "sha256=bad", "secret")


def test_parse_ignores_status_updates():
    status_only = {"entry": [{"changes": [{"value": {"statuses": [{"id": "x", "status": "read"}]}}]}]}
    assert meta_whatsapp.parse(status_only) == []
    [msg] = meta_whatsapp.parse(_payload("هلا"))
    assert (msg.phone, msg.name, msg.text) == (PATIENT, "Fatma", "هلا")


def test_webhook_replies_through_the_api(agent, monkeypatch):
    sent = []
    client = _client(agent, monkeypatch, sent)
    assert client.post("/meta", json=_payload("السلام عليكم")).status_code == 200
    assert sent and sent[0][0] == PATIENT and "Fatma" in sent[0][1]


def test_repeated_webhook_is_answered_once(agent, monkeypatch):
    sent = []
    client = _client(agent, monkeypatch, sent)
    client.post("/meta", json=_payload("السلام عليكم", msg_id="wamid.same"))
    client.post("/meta", json=_payload("السلام عليكم", msg_id="wamid.same"))
    assert len(sent) == 1


def test_bad_signature_is_rejected(agent, monkeypatch):
    client = _client(agent, monkeypatch, [])
    monkeypatch.setattr(config, "META_APP_SECRET", "secret")
    r = client.post("/meta", content=json.dumps(_payload("hi")), headers={"X-Hub-Signature-256": "sha256=bad",
                                                                           "content-type": "application/json"})
    assert r.status_code == 403


def test_staff_done_releases_and_bot_answers_again(agent, monkeypatch):
    sent = []
    client = _client(agent, monkeypatch, sent)
    monkeypatch.setattr(config, "STAFF_WHATSAPP", "+" + STAFF)
    client.post("/meta", json=_payload("ابي اكلم موظف", msg_id="m1"))
    hid = handoff.open_handoffs(agent.engine)[0]["id"]
    client.post("/meta", json=_payload("مرحبا", msg_id="m2"))          # silent: a human has the chat
    client.post("/meta", json=_payload(f"done {hid}", sender=STAFF, msg_id="m3"))
    client.post("/meta", json=_payload("مرحبا", msg_id="m4"))
    to_patient = [body for to, body in sent if to == PATIENT]
    assert len(to_patient) == 2                                          # handoff notice + welcome after release
    assert any(to == STAFF and "closed" in body for to, body in sent)
