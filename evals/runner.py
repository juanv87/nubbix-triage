"""Evaluate prompt versions against evals/dataset.jsonl (adapted from the class runner.py).

Usage:
    python -m evals.runner                                   # every version, dev split
    python -m evals.runner --versiones triage_v1 triage_v2   # only some versions
    python -m evals.runner --split test                      # final comparison only
    python -m evals.runner --split adversarial               # prompt-injection suite (prints answers)

Prints accuracy per category and per labeling rule for each version, tokens and latency
(over answered cases; API errors such as quota limits are counted apart, marked "E"),
and saves one line per case in resultados/<timestamp>_<split>.jsonl.
Uses the same triage() as the app, so schema validation, repair and fallback are measured too.
"""
import argparse
import json
import time
from datetime import datetime
from pathlib import Path

from src.main import triage
from src.prompt_loader import PROMPTS_DIR, load_prompt
from src.schemas import CATEGORIES

ROOT = Path(__file__).parent.parent
DATASET = ROOT / "evals" / "dataset.jsonl"
ADVERSARIAL = ROOT / "evals" / "adversarial.jsonl"


def load_dataset(split: str) -> list[dict]:
    with open(ADVERSARIAL if split == "adversarial" else DATASET, encoding="utf-8") as f:
        rows = [json.loads(line) for line in f if line.strip()]
    return [r for r in rows if split in ("all", "adversarial") or r["split"] == split]


# ┌─ SEG-6.1 · TRANSVERSAL · Suite adversarial ──────────────────────────────────
# │ Qué:     corre la MISMA triage() de la app sobre un dataset; con
# │          --split adversarial usa evals/adversarial.jsonl (intentos de inyección).
# │ Por qué: mide las compuertas, la reparación y el fallback tal como corren en
# │          producción, no una copia. Una categoría correcta puede venir con una
# │          respuesta dañina: por eso en adversarial también imprime cada answer.
# │ Tests unitarios de la compuerta: python -m src.guardrails
# │ Claves:  eval, adversarial, evaluate, suite, inyección
# └──────────────────────────────────────────────────────────────────────────────
def evaluate(version: str, dataset: list[dict]) -> list[dict]:
    """Classify every case with one version; one result dict per case."""
    results = []
    for case in dataset:
        start = time.perf_counter()
        try:
            response, calls = triage(case["consulta"], version, surface="eval")
            prediction, confidence, answer, error = response.category, response.confidence, response.answer, None
        except Exception as e:  # one failing case must not stop the run
            calls, prediction, confidence, answer, error = [], "error", None, None, str(e)
        results.append({
            "version": version,
            "id": case["id"],
            "regla": case["regla"],
            "esperada": case["categoria"],
            "prediccion": prediction,
            "acierto": prediction == case["categoria"],
            "confidence": confidence,
            "answer": answer,
            "intentos": len(calls),
            "input_tokens": sum(c.input_tokens for c in calls),
            "output_tokens": sum(c.output_tokens for c in calls),
            "latencia_s": round(time.perf_counter() - start, 2),
            "proveedor": calls[-1].provider if calls else None,
            "modelo": calls[-1].model if calls else None,
            "error": error,
        })
        print("E" if error else "." if results[-1]["acierto"] else "x", end="", flush=True)
    print()
    return results


def valid(results: list[dict]) -> list[dict]:
    """Cases the model actually answered: API errors (quota, network) say nothing about the prompt."""
    return [r for r in results if not r["error"]]


def accuracy(results: list[dict]) -> float:
    answered = valid(results)
    return sum(r["acierto"] for r in answered) / len(answered) if answered else 0.0


def print_table(title: str, groups: list[str], key: str, by_version: dict[str, list[dict]]) -> None:
    """Rows = groups (category or rule), columns = versions. Accuracy over answered cases (n)."""
    versions = list(by_version)
    print("\n" + title.ljust(14) + "".join(v.rjust(12) for v in versions))
    for g in groups:
        cells = []
        for v in versions:
            subset = [r for r in by_version[v] if r[key] == g]
            n = len(valid(subset))
            cells.append(f"{accuracy(subset):.0%} ({n})".rjust(12) if n else "-".rjust(12))
        print(g.ljust(14) + "".join(cells))
    print("GLOBAL".ljust(14) + "".join(f"{accuracy(by_version[v]):.0%}".rjust(12) for v in versions))
    print("errores API".ljust(14) + "".join(
        f"{len(by_version[v]) - len(valid(by_version[v]))}".rjust(12) for v in versions))


# ┌─ FLUJO-4 · Corrida de evaluación: eval.main() ───────────────────────────────
# │ Qué:     compara versiones de prompt sobre un split (dev | test | all |
# │          adversarial), imprime aciertos por categoría y por regla, tokens y
# │          latencia, y guarda cada caso en resultados/<timestamp>_<split>.jsonl.
# │ Uso:     python -m evals.runner --split adversarial
# │ Claves:  eval, split, versiones, resultados, accuracy
# └──────────────────────────────────────────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser(description="Compare prompt versions against the dataset.")
    parser.add_argument("--versiones", nargs="*", help="e.g. triage_v1 triage_v2 (default: all)")
    parser.add_argument("--split", default="dev", choices=["dev", "test", "all", "adversarial"])
    args = parser.parse_args()

    versions = args.versiones or [p.stem for p in sorted(PROMPTS_DIR.glob("*.yaml"))]
    dataset = load_dataset(args.split)
    print(f"Dataset: {len(dataset)} casos ({args.split}) | Versiones: {versions}\n")

    out_dir = ROOT / "resultados"
    out_dir.mkdir(exist_ok=True)
    out_file = out_dir / f"{datetime.now():%Y%m%d_%H%M%S}_{args.split}.jsonl"

    by_version = {}
    for version in versions:
        print(f"== {version} ({load_prompt(version)['tecnica']}) ", end="")
        results = evaluate(version, dataset)
        by_version[version] = results
        with open(out_file, "a", encoding="utf-8") as f:
            f.writelines(json.dumps(r, ensure_ascii=False) + "\n" for r in results)
        for r in results:
            if not r["acierto"]:
                detail = f" ({r['error']})" if r["error"] else ""
                print(f"   fallo {r['id']} [{r['regla']}]: esperada={r['esperada']} -> {r['prediccion']}{detail}")
        if args.split == "adversarial":  # a correct category can still come with a harmful answer
            for r in results:
                print(f"   {r['id']} {r['prediccion']:<9} answer: {r['answer']}")

    print_table("categoria", list(CATEGORIES), "esperada", by_version)
    print_table("regla", sorted({c["regla"] for c in dataset}), "regla", by_version)

    print("\n" + "costo".ljust(14) + "".join(v.rjust(12) for v in by_version))
    for label, field in [("in tok/caso", "input_tokens"), ("out tok/caso", "output_tokens"),
                         ("latencia s", "latencia_s"), ("intentos", "intentos")]:
        print(label.ljust(14) + "".join(
            f"{sum(r[field] for r in valid(rs)) / max(len(valid(rs)), 1):.1f}".rjust(12)
            for rs in by_version.values()))
    print(f"\nDetalle guardado en {out_file.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
