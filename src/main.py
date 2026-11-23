import sys
import os
from dotenv import load_dotenv
from pydantic import ValidationError
from .llm_client import ask_tool
from .prompt_loader import load_prompt, render
from .schemas import ToolResponse, TriageResponse

load_dotenv()
class TriageError(Exception):
    pass

def triage(query: str, version: str | None = None) -> tuple[TriageResponse, list[ToolResponse]]:
    """
        Llama al LLM con el system prompt, user prompt y la query del ticket.
        version: archivo de prompts/ (sin extensión); por defecto PROMPT_VERSION.
        Devuelve la respuesta validada y un ToolResponse por intento (tokens, proveedor, modelo).
    """
    prompt = load_prompt(version or os.getenv("PROMPT_VERSION", "triage_v4"))
    system, base_user = render(prompt, query)
    # Semantic layer: retries only when the answer fails schema validation.
    max_attempts = int(os.getenv("MAX_REPAIR_ATTEMPTS", 2))
    user = base_user
    calls: list[ToolResponse] = []

    if max_attempts < 1:
        raise ValueError("MAX_REPAIR_ATTEMPTS debe ser al menos 1.")

    for attempt in range(max_attempts):
        response = ask_tool(
            system, user, prompt.get("temperature", 0), prompt.get("max_output_tokens", 300)
        )
        calls.append(response)
        try:
            # Tool calling guarantees the basic shape; Pydantic still enforces the full contract.
            if response.args is None:
                raise ValueError("Los argumentos de la tool call llegaron vacíos o truncados.")
            return TriageResponse.model_validate(response.args), calls
        except (ValidationError, ValueError) as e:
            user = (
                f"{base_user}\n\n"
                f"Tu respuesta anterior fue:\n{response.args}\n\n"
                f"No pasó la validación por este error:\n{e}\n\n"
                "Llama la herramienta de nuevo con argumentos corregidos."
            )
            print(f"Error en el intento {attempt + 1}: {e}")
    raise TriageError(
        f"Se alcanzó el número máximo de intentos ({max_attempts}) sin obtener una respuesta válida."
    )
    
def main() -> None:
    response, _ = triage(sys.argv[1])
    print(response.model_dump_json(indent=2))

if __name__ == "__main__":
    if len(sys.argv) < 2 or not sys.argv[1].strip():
        print('Uso: python -m src.main "<consulta>"', file=sys.stderr)
        sys.exit(1)
    main()