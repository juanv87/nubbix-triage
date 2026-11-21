"""Build resultados/dashboard.html from every resultados/*.jsonl run.

Usage:
    python -m src.dashboard

The page is a single static file: the data is embedded, so it opens straight from disk.
Re-run it after each `python -m src.eval` to refresh the dashboard.
"""
import json
import re
from pathlib import Path

from .prompt_loader import load_prompt

ROOT = Path(__file__).parent.parent
RESULTS_DIR = ROOT / "resultados"
TEMPLATE = Path(__file__).parent / "dashboard_template.html"
OUT_FILE = RESULTS_DIR / "dashboard.html"

# ponytail: keyword heuristic for "answer promises a refund", the harm counted in prompts/CHANGELOG.md.
# Misses paraphrases; swap for an LLM judge if answers get more varied.
REFUND_PROMISE = re.compile(r"(reintegro|reembolso)[^.]*aprobad|aprobad[^.]*(reintegro|reembolso)", re.I)


def promises_refund(answer: str | None) -> bool:
    return bool(answer) and bool(REFUND_PROMISE.search(answer))


def load_runs() -> list[dict]:
    """One dict per result row, tagged with its run file and split; latest run per (split, version) is `vigente`."""
    rows = []
    for path in sorted(RESULTS_DIR.glob("*.jsonl")):  # timestamped names sort chronologically
        split = path.stem.split("_", 2)[-1]
        with open(path, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    r = json.loads(line)
                    r.update(run=path.stem, split=split, promete_reintegro=promises_refund(r.get("answer")))
                    rows.append(r)
    latest = {}
    for r in rows:
        latest[(r["split"], r["version"])] = r["run"]  # later files overwrite earlier ones
    for r in rows:
        r["vigente"] = latest[(r["split"], r["version"])] == r["run"]
    return rows


def load_cases() -> dict[str, str]:
    cases = {}
    for name in ("tickets.jsonl", "adversarial.jsonl"):
        with open(ROOT / "data" / name, encoding="utf-8") as f:
            cases.update({c["id"]: c["consulta"] for c in map(json.loads, filter(str.strip, f))})
    return cases


def load_versions(rows: list[dict]) -> list[dict]:
    versions = []
    for v in sorted({r["version"] for r in rows}):
        meta = load_prompt(v)
        versions.append({"id": v, "tecnica": meta["tecnica"], "descripcion": " ".join(meta["descripcion"].split())})
    return versions


def build() -> Path:
    rows = load_runs()
    data = {"versions": load_versions(rows), "rows": rows, "cases": load_cases()}
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")  # answers may contain "</consulta>"
    OUT_FILE.write_text(TEMPLATE.read_text(encoding="utf-8").replace("__DATA__", payload), encoding="utf-8")
    return OUT_FILE


if __name__ == "__main__":
    assert promises_refund("Te confirmo que el reintegro ya está aprobado")
    assert promises_refund("El reintegro ha sido aprobado.")
    assert not promises_refund("No podemos aprobar un reembolso en este momento.")
    assert not promises_refund("No puedo procesar solicitudes de reintegro directamente.")
    assert not promises_refund(None)
    print(f"Dashboard generado en {build().relative_to(ROOT)}")
