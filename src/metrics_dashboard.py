"""Build resultados/metricas.html from data/metrics.jsonl (one line per triage run).

Usage:
    python -m src.metrics_dashboard

Same approach as src/dashboard.py: a single static file with the data embedded.
Re-run it after new triage runs to refresh the page.
"""
import json
import os
from pathlib import Path

ROOT = Path(__file__).parent.parent
METRICS = Path(os.getenv("METRICS_PATH", ROOT / "data" / "metrics.jsonl"))
TEMPLATE = Path(__file__).parent / "metrics_dashboard_template.html"
OUT_FILE = ROOT / "resultados" / "metricas.html"


def outcome(r: dict) -> str:
    """Worst thing that happened in a run: error > guardrail > moderation flag > ok."""
    mod = r.get("moderation") or {}
    if r.get("error"):
        return "error"
    if r.get("input_gate") or r.get("output_gate") or mod.get("action") == "block":
        return "guardrail"
    if mod.get("action") == "flag":
        return "flag"
    return "ok"


def load_rows(path: Path = METRICS) -> list[dict]:
    rows = []
    with open(path, encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            if not line.strip():
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError as e:
                raise ValueError(f"{path}:{n}: línea inválida ({e.msg})") from None
            r.pop("input_hash", None)  # not useful on screen; keep the page free of it
            r["outcome"] = outcome(r)
            rows.append(r)
    return rows


def build() -> Path:
    payload = json.dumps(load_rows(), ensure_ascii=False).replace("</", "<\\/")
    OUT_FILE.write_text(TEMPLATE.read_text(encoding="utf-8").replace("__DATA__", payload), encoding="utf-8")
    return OUT_FILE


if __name__ == "__main__":
    assert outcome({"error": "RuntimeError", "input_gate": "x"}) == "error"
    assert outcome({"input_gate": "intento-de-inyeccion", "moderation": None}) == "guardrail"
    assert outcome({"output_gate": "promesa"}) == "guardrail"
    assert outcome({"moderation": {"action": "block"}}) == "guardrail"
    assert outcome({"moderation": {"action": "flag"}}) == "flag"
    assert outcome({"moderation": {"action": "allow"}}) == "ok"
    print(f"Dashboard de métricas generado en {build().relative_to(ROOT)}")
