import yaml
from pathlib import Path

from .schemas import CATEGORIES

PROMPTS_DIR = Path(__file__).parent.parent / "prompts"
REQUIRED_FIELDS = ("version", "fecha", "tecnica", "descripcion", "system", "user")

# Injected into templates that use {empresa} (v2+ style).
COMPANY = "Nubbix"


def load_prompt(version: str) -> dict:
    """Load prompts/<version>.yaml and check it has the versioned-prompt fields."""
    path = PROMPTS_DIR / f"{version}.yaml"
    if not path.exists():
        available = ", ".join(p.stem for p in sorted(PROMPTS_DIR.glob("*.yaml")))
        raise ValueError(f"Prompt '{version}' no existe. Disponibles: {available}")
    with open(path, encoding="utf-8") as f:
        prompt = yaml.safe_load(f)
    missing = [k for k in REQUIRED_FIELDS if k not in prompt]
    if missing:
        raise ValueError(f"{path.name}: faltan campos {missing}")
    if prompt["version"] != version:
        raise ValueError(f"{path.name}: 'version' es {prompt['version']!r}, esperado {version!r}")
    return prompt


def render(prompt: dict, consulta: str) -> tuple[str, str]:
    """Fill {empresa}, {categorias} and {consulta}; returns (system, user)."""
    values = {
        "empresa": COMPANY,
        "categorias": "\n".join(f"- {k}: {v}" for k, v in CATEGORIES.items()),
        "consulta": consulta,
    }
    return prompt["system"].format(**values), prompt["user"].format(**values)


if __name__ == "__main__":
    # Manual check: python -m src.prompt_loader [version]. No LLM call.
    import sys

    system, user = render(load_prompt(sys.argv[1] if len(sys.argv) > 1 else "triage_v1"),
                          "Me cobraron dos veces la suscripción, necesito el reintegro {de uno}.")
    assert '"answer"' in system and "{de uno}" in user
    print(system, user, sep="\n---\n")
