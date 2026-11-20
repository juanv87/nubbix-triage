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

from src.schemas import LLMResult

load_dotenv()

# Transport layer: the SDKs retry transient errors (408/429/5xx/timeout/connection)
# with exponential backoff. LLM_HTTP_MAX_RETRIES counts retries, not total attempts.
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

def call_gemini(system, user, temperature, max_output_tokens) -> LLMResult:
    response = client_gemini.models.generate_content(
        model=MODELS["gemini"],
        contents=user,
        config=types.GenerateContentConfig(
            system_instruction=system,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            response_mime_type="application/json"
        ),
    )
    if response is None:
        raise ValueError("No se recibió respuesta del modelo.")
    if response.text is None:
        raise ValueError("La respuesta del modelo es nula.")
    if response.usage_metadata is None:
        raise ValueError(f"Metadata vacía en {MODELS["gemini"]}")
    return LLMResult(
        text=response.text,
        provider="gemini",
        model=MODELS["gemini"],
        input_tokens=response.usage_metadata.prompt_token_count or 0,
        output_tokens=(response.usage_metadata.thoughts_token_count or 0) + (response.usage_metadata.candidates_token_count or 0),
    )

def call_openai(system, user, temperature, max_output_tokens) -> LLMResult:
    response = client_openai.chat.completions.create(
        model=MODELS["openai"],
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user}
        ],
        temperature=temperature,
        max_tokens=max_output_tokens,
        response_format={"type": "json_object"}
    )
    if response is None or len(response.choices) == 0:
        raise ValueError("No se recibió respuesta del modelo.")
    if response.choices[0].message.content is None:
        raise ValueError("La respuesta del modelo es nula.")
    if response.usage is None:
            raise ValueError(f"Metadata vacía {MODELS["openai"]}")
    return LLMResult(
        text=response.choices[0].message.content,
        provider="openai",
        model=MODELS["openai"],
        input_tokens=response.usage.prompt_tokens,
        output_tokens=response.usage.completion_tokens,
    )


PROVIDERS = {"openai": call_openai, "gemini": call_gemini}
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


def call_llm(system, user, temperature, max_output_tokens) -> LLMResult:
    provider = os.getenv("LLM_PROVIDER", "openai")
    fallback_provider = os.getenv("LLM_FALLBACK_PROVIDER", "gemini")

    if provider not in PROVIDERS or fallback_provider not in PROVIDERS:
        raise ValueError(f"El provedor asignado no existe. Opciones válidas: {", ".join(PROVIDERS)}.")
    try:
        result = PROVIDERS[provider](system, user, temperature, max_output_tokens)
        return result
    except API_ERRORS as e:
        if not is_transient(e):
            raise
        print(f"Error en el llamado a la API de {provider}. {e}")
        try:
            print(f"Probando con {fallback_provider}: \n")
            result = PROVIDERS[fallback_provider](system, user, temperature, max_output_tokens)
            return result
        except API_ERRORS as e:
            raise RuntimeError(f"Todos los provedores fallaron. {e}") from e
