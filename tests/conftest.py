from datetime import datetime

import pytest

from clinic import config
from clinic.agent import Agent
from clinic.db import make_engine
from data.seed import seed

NOW = datetime(2026, 10, 4, 10, 0)  # Sunday 10:00, Kuwait time


@pytest.fixture(autouse=True)
def no_llm(monkeypatch):
    """Tests never call Gemini; individual tests patch llm.generate when they need it."""
    monkeypatch.setattr(config, "GEMINI_API_KEY", "")


@pytest.fixture
def engine(tmp_path):
    eng = make_engine(f"sqlite:///{tmp_path / 'test.db'}")
    seed(eng, busy_days=0)
    yield eng
    eng.dispose()


@pytest.fixture
def alerts():
    return []


@pytest.fixture
def agent(engine, alerts):
    return Agent(engine, notify=lambda to, body: alerts.append((to, body)), clock=lambda: NOW,
                 staff_to="whatsapp:+96511112222")
