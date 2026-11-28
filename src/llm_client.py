import json
import os

from dotenv import load_dotenv
from google import genai
from google.genai import types
from openai import OpenAI
import openai
from google.genai import errors as genai_errors
# ponytail: private SDK tuple (timeout/connect errors for httpx or httpx2, whichever is
# installed). Pinned google-genai keeps it stable; if an upgrade removes it, list them here.
from google.genai._api_client import _HTTPX_TRANSIENT_EXC as GEMINI_NETWORK_ERRORS

from src.schemas import ToolResponse, TriageResponse

load_dotenv()

# ┌─ SEG-3.3 · INFERENCIA · Timeout y reintentos (capa de transporte) ───────────
# │ Qué:     los SDK reintentan errores transitorios (408/429/5xx/timeout/conexión)
# │          con backoff exponencial y cortan cada llamada a los LLM_TIMEOUT segundos.
# │ Ojo:     LLM_HTTP_MAX_RETRIES cuenta REINTENTOS; Gemini cuenta intentos totales
# │          (por eso el +1 abajo).
# │ Ver:     ask_tool() (fallback de proveedor, misma SEG-3.3)
# │ Claves:  timeout, reintentos, retries, backoff, LLM_TIMEOUT
# └──────────────────────────────────────────────────────────────────────────────
TIMEOUT_S = float(os.getenv("LLM_TIMEOUT", 20))
HTTP_MAX_RETRIES = int(os.getenv("LLM_HTTP_MAX_RETRIES", 2))

client_openai = OpenAI(max_retries=HTTP_MAX_RETRIES, timeout=TIMEOUT_S)
client_gemini = genai.Client(
    api_key=os.getenv("GEMINI_API_KEY"),
    http_options=types.HttpOptions(
        # Gemini counts total attempts, including the initial request.
        retry_options=types.HttpRetryOptions(attempts=HTTP_MAX_RETRIES + 1),
        timeout=int(TIMEOUT_S * 1000),
    ),
)
MODELS = {
    "gemini": os.getenv("GEMINI_MODEL", "gemini-3.5-flash"),
    "openai": os.getenv("OPENAI_MODEL", "gpt-4o-mini")
}

# ┌─ SEG-3.2 · INFERENCIA · Tool calling forzado ────────────────────────────────
# │ Qué:     el modelo está obligado a llamar a la herramienta clasificar_consulta;
# │          no puede responder texto libre.
# │          OpenAI: tool_choice con la función nombrada (ask_tool_openai).
# │          Gemini: FunctionCallingConfigMode.ANY + allowed_function_names.
# │ Fuente única: el esquema sale del contrato Pydantic (SEG-4.1), así lo que se
# │          le exige al modelo y lo que se valida después nunca se desalinean.
# │ Claves:  tool calling, function calling, tool_choice, TOOL_SCHEMA
# └──────────────────────────────────────────────────────────────────────────────
TOOL_NAME = "clasificar_consulta"
TOOL_SCHEMA = TriageResponse.model_json_schema()


def ask_tool_gemini(system, user, temperature, max_output_tokens) -> ToolResponse:
    """
    Usa FunctionCallingConfigMode.ANY con allowed_function_names. Los args ya llegan como dict.
    """
    response = client_gemini.models.generate_content(
        model=MODELS["gemini"],
        contents=user,
        config=types.GenerateContentConfig(
            # SEG-3.1 · INFERENCIA · Roles: en Gemini las reglas van como system_instruction.
            system_instruction=system,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            tools=[types.Tool(function_declarations=[
                types.FunctionDeclaration(
                    name=TOOL_NAME,
                    description="Clasifica la consulta del cliente.",
                    parameters_json_schema=TOOL_SCHEMA,
                )
            ])],
            tool_config=types.ToolConfig(
                function_calling_config=types.FunctionCallingConfig(
                    mode=types.FunctionCallingConfigMode.ANY,
                    allowed_function_names=[TOOL_NAME],
                )
            ),
        ),
    )
    if response is None or response.usage_metadata is None:
        raise ValueError(f"Respuesta o metadata vacía en {MODELS['gemini']}")
    calls = response.function_calls or []
    usage = response.usage_metadata
    return ToolResponse(
        # Gemini already delivers a dict; None only if no call came back.
        args=dict(calls[0].args) if calls and calls[0].args is not None else None,
        provider="gemini",
        model=MODELS["gemini"],
        input_tokens=usage.prompt_token_count or 0,
        output_tokens=(usage.thoughts_token_count or 0) + (usage.candidates_token_count or 0),
    )


def ask_tool_openai(system, user, temperature, max_output_tokens) -> ToolResponse:
    """
    Fuerza el tool_choice y hace json.loads. Si el JSON llega truncado, devuelve args=None.
    """
    response = client_openai.chat.completions.create(
        model=MODELS["openai"],
        # ┌─ SEG-3.1 · INFERENCIA · Roles system / user ───────────────────────────
        # │ Qué:     las reglas viajan con role "system" y la consulta con role "user".
        # │ Por qué: el modelo prioriza el rol system; el texto del cliente nunca se
        # │          mezcla con las reglas en un mismo mensaje (ver SEG-2.3).
        # │ Claves:  roles, system, user, messages
        # └────────────────────────────────────────────────────────────────────────
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=temperature,
        max_tokens=max_output_tokens,
        tools=[{
            "type": "function",
            "function": {"name": TOOL_NAME, "parameters": TOOL_SCHEMA},
        }],
        tool_choice={"type": "function", "function": {"name": TOOL_NAME}},
    )
    if response is None or len(response.choices) == 0:
        raise ValueError("No se recibió respuesta del modelo.")
    if response.usage is None:
        raise ValueError(f"Metadata vacía {MODELS['openai']}")
    # The SDK types tool_calls as function | custom; only function calls carry `.function`.
    tool_calls = [tc for tc in response.choices[0].message.tool_calls or [] if tc.type == "function"]
    args = None
    if tool_calls:
        try:
            # OpenAI delivers a string; it can be truncated (finish_reason="length").
            args = json.loads(tool_calls[0].function.arguments)
        except json.JSONDecodeError:
            args = None
    return ToolResponse(
        args=args,
        provider="openai",
        model=MODELS["openai"],
        input_tokens=response.usage.prompt_tokens,
        output_tokens=response.usage.completion_tokens,
    )


PROVIDERS = {"openai": ask_tool_openai, "gemini": ask_tool_gemini}
# Gemini network errors surface as raw httpx exceptions once its retries run out.
API_ERRORS = (openai.APIError, genai_errors.APIError, *GEMINI_NETWORK_ERRORS)
TRANSIENT_STATUS = {408, 409, 429}


def is_transient(e: Exception) -> bool:
    """True for errors another provider might not have: network, rate limit, 5xx.
    Config errors (400/401/403/404) are False so the fallback does not hide them."""
    if isinstance(e, (openai.APIConnectionError, *GEMINI_NETWORK_ERRORS)):
        return True
    # OpenAI exposes `status_code`, Gemini exposes `code`.
    status = getattr(e, "status_code", None) or getattr(e, "code", None)
    return isinstance(status, int) and (status in TRANSIENT_STATUS or status >= 500)


# ┌─ SEG-3.3 · INFERENCIA · Fallback de proveedor ───────────────────────────────
# │ Qué:     llama al proveedor principal (LLM_PROVIDER) y, si falla con un error
# │          TRANSITORIO (is_transient: red, 429, 5xx), prueba con LLM_FALLBACK_PROVIDER.
# │ Por qué: errores de configuración (400/401/403/404) se propagan tal cual; si
# │          el fallback los tapara, una API key rota pasaría desapercibida.
# │ Claves:  fallback, proveedor, provider, is_transient, ask_tool
# └──────────────────────────────────────────────────────────────────────────────
def ask_tool(system, user, temperature, max_output_tokens) -> ToolResponse:
    """Forces the TriageResponse tool call; .args is a normalized dict (or None if parsing failed)."""
    provider = os.getenv("LLM_PROVIDER", "openai")
    fallback_provider = os.getenv("LLM_FALLBACK_PROVIDER", "gemini")

    if provider not in PROVIDERS or fallback_provider not in PROVIDERS:
        raise ValueError(f"El provedor asignado no existe. Opciones válidas: {", ".join(PROVIDERS)}.")
    try:
        return PROVIDERS[provider](system, user, temperature, max_output_tokens)
    except API_ERRORS as e:
        if not is_transient(e):
            raise
        print(f"Error en el llamado a la API de {provider}. {e}")
        try:
            print(f"Probando con {fallback_provider}: \n")
            return PROVIDERS[fallback_provider](system, user, temperature, max_output_tokens)
        except API_ERRORS as e:
            raise RuntimeError(f"Todos los provedores fallaron. {e}") from e

