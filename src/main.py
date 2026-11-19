import sys
import os
from dotenv import load_dotenv
from pydantic import ValidationError
from .llm_client import call_llm
from .prompt_loader import load_prompt
from .schemas import TriageResponse

load_dotenv()
class TriageError(Exception):
    pass

def triage(query: str) -> TriageResponse:
    """
        Llama al LLM con el system prompt, user prompt y la query del ticket.
    """
    prompt = load_prompt("v1_zero_shot")
    user = prompt["user_template"].format(query=query)
    system = prompt["system"]
    max_attempts = int(os.getenv("MAX_ATTEMPTS", 2))
    base_user = prompt["user_template"].format(query=query)
    user = base_user
    
    if max_attempts < 1:
        raise ValueError("max_attempts debe ser al menos 1.")

    for attempt in range(max_attempts):
        response_content = call_llm(system, user)
        try:
            return TriageResponse.model_validate_json(
                response_content.text
            )
        except ValidationError as e:
            user = (
                f"{base_user}\n\n"
                f"Your previous answer was:\n{response_content.text}\n\n"
                f"It failed validation with this error:\n{e}\n\n"
                "Return only a corrected JSON object."
            )
            print(f"Error en el intento {attempt + 1}: {e}")
    raise TriageError(
        f"Se alcanzó el número máximo de intentos ({max_attempts}) sin obtener una respuesta válida."
    )
    
def main() -> None:
    print(triage(sys.argv[1]).model_dump_json(indent=2))

if __name__ == "__main__":
    if len(sys.argv) < 2 or not sys.argv[1].strip():
        print('Uso: python -m src.main "<consulta>"', file=sys.stderr)
        sys.exit(1)
    main()