import os
from .guardrails import decide, load_thresholds
from .llm_client import client_openai

THRESHOLDS = load_thresholds()  # fail fast: a malformed config must stop the import

# ponytail: tiny keyword table for offline tests/dev; the real classifier is OpenAI.
_MOCK = {
    "idiota": {"harassment": 0.6},
    "idiot": {"harassment": 0.6},
    "te voy a matar": {"violence": 0.9, "harassment/threatening": 0.9},
}

def moderate_openai(text: str) -> dict[str, float]:
    res = client_openai.moderations.create(model="omni-moderation-latest", input=text)
    # by_alias keeps keys like "harassment/threatening", the ones config/moderation.yaml uses.
    scores = res.results[0].category_scores.model_dump(by_alias=True)
    return {k: v for k, v in scores.items() if v is not None}

def moderate_mock(text: str) -> dict[str, float]:
    low, scores = text.lower(), {}
    for kw, s in _MOCK.items():
        if kw in low:
            for cat, v in s.items():
                scores[cat] = max(v, scores.get(cat, 0))
    return scores

_PROVIDERS = {"openai": moderate_openai, "mock": moderate_mock}

# ┌─ SEG-1.6 · ENTRADA · Moderación de contenido: moderate() ────────────────────
# │ Qué:     obtiene scores por categoría del proveedor (MODERATION_PROVIDER:
# │          openai | mock | off) y los pasa a guardrails.decide (umbrales).
# │ Fail-closed: si el clasificador falla, NUNCA devuelve allow: devuelve flag
# │          con "moderation_unavailable" y solo el nombre de la excepción.
# │ Devuelve: (action, reasons, severity). Lo llama main._triage.
# │ Claves:  moderate, moderación, fail-closed, MODERATION_PROVIDER, omni-moderation
# └──────────────────────────────────────────────────────────────────────────────
def moderate(text: str) -> tuple[str, list[dict], str]:
    provider = os.getenv("MODERATION_PROVIDER", "openai")
    if provider == "off":
        return "allow", [], "low"
    if provider not in _PROVIDERS:
        raise ValueError(f"MODERATION_PROVIDER inválido: {provider!r} (openai|mock|off)")
    try:
        scores = _PROVIDERS[provider](text)
    except Exception as e:
        # Fail-closed: if the classifier fails, never allow. Only the class name is kept.
        return "flag", [{"code": "moderation_unavailable", "description": type(e).__name__, "source": "rule"}], "medium"
    return decide(scores, THRESHOLDS["thresholds"])

if __name__ == "__main__":
    def with_env(value, fn):
        old = os.environ.get("MODERATION_PROVIDER")
        os.environ["MODERATION_PROVIDER"] = value
        try:
            return fn()
        finally:
            if old is None:
                os.environ.pop("MODERATION_PROVIDER", None)
            else:
                os.environ["MODERATION_PROVIDER"] = old

    assert with_env("mock", lambda: moderate("hola, no puedo entrar")) == ("allow", [], "low")
    a, r, _ = with_env("mock", lambda: moderate("sos un idiota"))
    assert a == "flag" and [x["code"] for x in r] == ["harassment"]
    assert with_env("mock", lambda: moderate("te voy a matar"))[0] == "block"
    assert with_env("off", lambda: moderate("te voy a matar")) == ("allow", [], "low")
    try:
        with_env("nope", lambda: moderate("x"))
        raise AssertionError("invalid provider accepted")
    except ValueError:
        pass

    def boom(text):
        raise RuntimeError("secret detail")
    _PROVIDERS["mock"] = boom
    a, r, sev = with_env("mock", lambda: moderate("x"))
    assert a == "flag" and sev == "medium"
    assert r == [{"code": "moderation_unavailable", "description": "RuntimeError", "source": "rule"}]

    th = {**THRESHOLDS["thresholds"], "harassment/threatening": {"allow": 0.1, "block": 0.5}}
    assert decide({"harassment/threatening": 0.3}, th)[0] == "flag"
    assert decide({"harassment/threatening": 0.5}, th)[0] == "block"
    assert "harassment/threatening" in decide({"harassment/threatening": 0.6}, THRESHOLDS["thresholds"])[1][0]["code"]
    print("ok")
