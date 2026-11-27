"""Repair loop check: python -m src.test_repair (no LLM calls, ask_tool is faked)."""
from . import main

LEAK = "LEAK-SECRET-123"
BAD = {"answer": LEAK, "confidence": 5, "category": "nope", "actions": []}
GOOD = {"answer": "Revisamos tu consulta.", "confidence": 0.9, "category": "billing", "actions": []}


def run(queue):
    users = []

    def fake(system, user, *_):
        users.append(user)
        return main.ToolResponse(args=queue.pop(0), provider="openai", model="fake", input_tokens=1, output_tokens=1)

    main.ask_tool = fake
    return main.triage("cobro duplicado"), users


(result, calls), users = run([BAD, GOOD])
assert result.category == "billing" and len(calls) == 2
# The retry names the failing fields but never echoes the rejected model output.
assert "confidence" in users[1] and "category" in users[1]
assert LEAK not in users[1] and "nope" not in users[1]

# Truncated args (None) also repair, and exhausting the attempts raises.
(result, _), _ = run([None, GOOD])
assert result.category == "billing"
try:
    run([BAD, BAD])
    raise AssertionError("expected TriageError")
except main.TriageError:
    pass
print("ok")
