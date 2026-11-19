import os

from dotenv import load_dotenv
from google import genai
from google.genai import types
from openai import OpenAI
import openai
from google.genai import errors as genai_errors

from src.schemas import LLMResult

load_dotenv()

client_openai = OpenAI(max_retries=2, timeout=20.0)
client_gemini = genai.Client(
    api_key=os.getenv("GEMINI_API_KEY"),
    http_options=types.HttpOptions(
        retry_options=types.HttpRetryOptions(attempts=3),
        timeout=20_000,
    ),
)
MODELS = {
    "gemini": os.getenv("GEMINI_MODEL", "gemini-3.5-flash"),
    "openai": os.getenv("OPENAI_MODEL", "gpt-4o-mini")
}

def call_gemini(system, user) -> LLMResult:
    response = client_gemini.models.generate_content(
        model=MODELS["gemini"],
        contents=user,
        config=types.GenerateContentConfig(
            system_instruction=system,
            temperature=0,
            max_output_tokens=300,
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

def call_openai(system, user) -> LLMResult:
    response = client_openai.chat.completions.create(
        model=MODELS["openai"],
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user}
        ],
        temperature=0,
        max_tokens=300,
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
API_ERRORS = (openai.APIError, genai_errors.APIError)

def call_llm(system, user) -> LLMResult:
    provider = os.getenv("LLM_PROVIDER", "openai")
    fallback_provider = os.getenv("LLM_FALLBACK_PROVIDER", "gemini")

    if provider not in PROVIDERS or fallback_provider not in PROVIDERS:
        raise ValueError(f"El provedor asignado no existe. Opciones válidas: {", ".join(PROVIDERS)}.")
    try:
        result = PROVIDERS[provider](system, user)
        return result
    except API_ERRORS as e:
        print(f"Error en el llamado a la API de {provider}. {e}")
        try:
            print(f"Probando con {fallback_provider}: \n")
            result = PROVIDERS[fallback_provider](system, user)
            return result
        except API_ERRORS as e:
            raise RuntimeError(f"Todos los provedores fallaron. {e}") from e
