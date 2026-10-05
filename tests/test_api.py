from fastapi.testclient import TestClient

from clinic import api, config, whatsapp


def _client(agent, monkeypatch):
    monkeypatch.setattr(api, "get_agent", lambda: agent)
    monkeypatch.setattr(api, "get_engine", lambda: agent.engine)
    return TestClient(api.app)


def test_signature_matches_twilio_example():
    # example from Twilio's webhook security docs
    params = {"CallSid": "CA1234567890ABCDE", "Caller": "+12349013030", "Digits": "1234",
              "From": "+12349013030", "To": "+18005551212"}
    assert whatsapp.signature_ok("https://mycompany.com/myapp.php?foo=1&bar=2", params, "0/KCTR6DLpKmkAf8muzZqo1nDgQ=", "12345")
    assert not whatsapp.signature_ok("https://mycompany.com/myapp.php?foo=1&bar=2", params, "wrong", "12345")


def test_webhook_replies_with_twiml(agent, monkeypatch):
    monkeypatch.setattr(config, "TWILIO_AUTH_TOKEN", "")
    client = _client(agent, monkeypatch)
    r = client.post("/whatsapp", data={"From": "whatsapp:+96560001111", "Body": "السلام عليكم", "ProfileName": "Fatma"})
    assert r.status_code == 200 and "<Message>" in r.text and "Fatma" in r.text


def test_webhook_rejects_bad_signature(agent, monkeypatch):
    monkeypatch.setattr(config, "TWILIO_AUTH_TOKEN", "secret")
    client = _client(agent, monkeypatch)
    r = client.post("/whatsapp", data={"From": "whatsapp:+96560001111", "Body": "hi"},
                    headers={"X-Twilio-Signature": "nope"})
    assert r.status_code == 403


def test_staff_can_release_a_handoff_over_whatsapp(agent, monkeypatch):
    monkeypatch.setattr(config, "TWILIO_AUTH_TOKEN", "")
    monkeypatch.setattr(config, "STAFF_WHATSAPP", "whatsapp:+96511112222")
    client = _client(agent, monkeypatch)
    hid = agent.chat("+96560001111", "ابي اكلم موظف").handoff_id
    r = client.post("/whatsapp", data={"From": "whatsapp:+96511112222", "Body": f"done {hid}"})
    assert "closed" in r.text
    assert agent.chat("+96560001111", "مرحبا").route == "smalltalk"


def test_demo_page_only_exposes_demo_chats(agent, monkeypatch):
    client = _client(agent, monkeypatch)
    assert client.get("/demo").status_code == 200
    real = agent.chat("+96560001111", "ابي اكلم موظف").handoff_id
    demo = agent.chat("+99912345678", "ابي اكلم موظف").handoff_id
    assert [h["id"] for h in client.get("/demo/handoffs").json()] == [demo]
    assert client.post(f"/demo/handoffs/{real}/release").status_code == 404
    assert client.post(f"/demo/handoffs/{demo}/release").status_code == 200
    assert agent.chat("+99912345678", "مرحبا").route == "smalltalk"
