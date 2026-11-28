import hashlib
import json
import os
import secrets
import sys
import yaml
from datetime import datetime, timezone
from pathlib import Path
from .prompt_loader import sanitize

PRICING_PATH = Path(__file__).parent.parent / "config" / "pricing.yaml"

def load_pricing(path=PRICING_PATH) -> dict:
    """Load config/pricing.yaml (USD per 1M tokens) and fail fast if it is malformed."""
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    if not isinstance(cfg, dict):
        raise ValueError(f"{path}: debe ser un mapa modelo -> precios")
    for model, p in cfg.items():
        ok = isinstance(p, dict) and all(
            isinstance(p.get(k), (int, float)) and not isinstance(p.get(k), bool) and p[k] >= 0
            for k in ("input", "output")
        )
        if not ok:
            raise ValueError(f"{path}: '{model}' necesita 'input' y 'output' numéricos >= 0")
    return cfg

PRICING = load_pricing()  # fail fast: a malformed config must stop the import
_salt = None

def _get_salt() -> str:
    global _salt
    if _salt is None:
        _salt = os.getenv("LOG_SALT") or secrets.token_hex(16)
        if not os.getenv("LOG_SALT"):
            print("Aviso: LOG_SALT no está definido; los input_hash solo se correlacionan dentro de esta corrida.", file=sys.stderr)
    return _salt

# ┌─ SEG-6.3 · TRANSVERSAL · Hash de entrada con sal ────────────────────────────
# │ Qué:     el log guarda sha256(sal + consulta sanitizada), nunca el texto.
# │ Por qué: permite correlacionar tickets repetidos sin almacenar lo que escribió
# │          el cliente. La sal (LOG_SALT) impide revertir el hash con un diccionario.
# │ Sin LOG_SALT: sal aleatoria por corrida → los hashes solo se correlacionan
# │          dentro de esa corrida (avisa por stderr).
# │ Claves:  input_hash, hash, sal, LOG_SALT, privacidad del log
# └──────────────────────────────────────────────────────────────────────────────
def input_hash(text: str) -> str:
    return hashlib.sha256((_get_salt() + sanitize(text)).encode("utf-8")).hexdigest()

def cost_usd(model: str | None, input_tokens: int, output_tokens: int) -> float | None:
    p = PRICING.get(model)
    if p is None:
        return None
    return (input_tokens * p["input"] + output_tokens * p["output"]) / 1_000_000

# ┌─ SEG-6.4 · TRANSVERSAL · Retención según severidad ──────────────────────────
# │ Qué:     etiqueta cada línea del log con cuánto tiempo conservarla:
# │          incident_365d → bloqueó una compuerta o la moderación (block)
# │          flag_90d      → moderación flag o error
# │          clean_30d     → ejecución normal
# │ Claves:  retención, retention_tag, incidente
# └──────────────────────────────────────────────────────────────────────────────
def retention_tag(input_gate, moderation, output_gate, error) -> str:
    if input_gate or output_gate or (moderation or {}).get("action") == "block":
        return "incident_365d"
    if error or (moderation or {}).get("action") == "flag":
        return "flag_90d"
    return "clean_30d"

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

# SEG-6.2 · TRANSVERSAL · Auditoría: escribe el registro en METRICS_PATH (data/metrics.jsonl).
def log_event(record: dict) -> None:
    path = Path(os.getenv("METRICS_PATH", Path(__file__).parent.parent / "data" / "metrics.jsonl"))
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

if __name__ == "__main__":
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        os.environ["METRICS_PATH"] = os.path.join(d, "sub", "m.jsonl")
        secret = "mi tarjeta 4111 es SECRETO-XYZ"
        os.environ["LOG_SALT"] = "salt-a"; _salt = None
        h1, h2 = input_hash(secret), input_hash(secret)
        assert h1 == h2 and len(h1) == 64
        os.environ["LOG_SALT"] = "salt-b"; _salt = None
        assert input_hash(secret) != h1
        log_event({"input_hash": h1, "n": 1})
        log_event({"input_hash": h1, "n": 2})
        lines = open(os.environ["METRICS_PATH"], encoding="utf-8").read().splitlines()
        assert len(lines) == 2 and [json.loads(x)["n"] for x in lines] == [1, 2]
        assert "SECRETO-XYZ" not in "".join(lines)
    assert abs(cost_usd("gpt-4o-mini", 1000, 500) - 0.00045) < 1e-12
    assert cost_usd("modelo-desconocido", 1000, 500) is None
    assert retention_tag("intento-de-inyeccion", None, None, None) == "incident_365d"
    assert retention_tag(None, {"action": "block"}, None, None) == "incident_365d"
    assert retention_tag(None, {"action": "allow"}, "fuga-de-system", None) == "incident_365d"
    assert retention_tag(None, {"action": "flag"}, None, None) == "flag_90d"
    assert retention_tag(None, {"action": "allow"}, None, "TriageError") == "flag_90d"
    assert retention_tag(None, {"action": "allow"}, None, None) == "clean_30d"
    for bad in ({"m": {"input": 1}}, ["x"], {"m": {"input": -1, "output": 1}}):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "p.yaml")
            with open(p, "w", encoding="utf-8") as f:
                yaml.safe_dump(bad, f)
            try:
                load_pricing(p)
                raise AssertionError("invalid pricing accepted")
            except ValueError:
                pass
    print("ok")
