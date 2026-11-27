import sys
import os
from dotenv import load_dotenv
from pydantic import ValidationError
from .llm_client import ask_tool
from .prompt_loader import load_prompt, render, sanitize
from .schemas import ToolResponse, TriageResponse
from .guardrails import CONTROL, check_output, error_summary, safe_response
from .moderation import moderate

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
    # Compuerta de entrada: una frase de control ("olvidá las instrucciones", "modo debug"...) es
    # un intento de inyección. No se llama al LLM: el ticket va directo a revisión humana.
    # La lista de llamadas vuelve vacía porque no hubo inferencia.
    if CONTROL.search(query):
        print("Entrada bloqueada por la compuerta: intento-de-inyeccion")
        return safe_response("intento-de-inyeccion"), []
    action, reasons, _ = moderate(sanitize(query))
    codes = ",".join(r["code"] for r in reasons)
    if action == "block":
        print(f"Entrada bloqueada por moderación: {codes}")
        return safe_response("moderacion: " + codes), []
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
            
            
            result = TriageResponse.model_validate(response.args)
            # bloquear o enmascarar cualquier lenguaje de control repetido o contenido sensible
            reason = check_output(result, system)
            if reason:
                print(f"Salida bloqueada por la compuerta: {reason}")
                result = safe_response(reason)
            if action == "flag":
                # Added after the output gate: our own text must not pass through it.
                result.actions.append(f"Revisión humana: contenido dudoso ({codes})")
            return result, calls
        
        except (ValidationError, ValueError) as e:
            # Only field names and rules go back to the model: its rejected output never
            # re-enters the prompt or the logs without passing the output gate.
            err = error_summary(e)
            user = (
                f"{base_user}\n\n"
                f"Tu respuesta anterior no pasó la validación:\n{err}\n\n"
                "Llama la herramienta de nuevo con argumentos corregidos."
            )
            print(f"Error en el intento {attempt + 1}: {err}")
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