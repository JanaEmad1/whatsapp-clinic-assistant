"""Chat with the assistant in the terminal — no WhatsApp or server needed.

    python -m clinic.cli            (type 'quit' to exit, 'release' to end a handoff)
"""
from __future__ import annotations

import sys

from clinic import handoff
from clinic.agent import Agent
from clinic.db import get_engine

PHONE = "+96599990000"


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stdin.reconfigure(encoding="utf-8")
    agent = Agent(get_engine(), notify=lambda to, body: print(f"\n[staff alert → {to}]\n{body}\n"),
                  staff_to="whatsapp:+96500000000")
    while True:
        try:
            message = input("you> ").strip()
        except EOFError:
            break
        if message == "quit":
            break
        if message == "release":
            for h in handoff.open_handoffs(agent.engine):
                handoff.release(agent.engine, h["id"], agent.clock())
            print("bot> (handoff closed — I'm back)")
            continue
        reply = agent.chat(PHONE, message, "Test")
        print(f"bot> {reply.answer or '(silent — a human has this chat)'}\n     [{reply.route}"
              f"{' ' + ','.join(reply.sources) if reply.sources else ''}"
              f"{f' score={reply.score}' if reply.score is not None else ''}]")


if __name__ == "__main__":
    main()
