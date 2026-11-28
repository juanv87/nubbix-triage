# ┌─ MAPA · Índice de controles de seguridad del triage ─────────────────────────
# │ Cada control tiene un recuadro como este con su ID: SEG-<etapa>.<control>.
# │ Buscar "SEG-1." lista toda la Entrada; "SEG-" lista todos; "FLUJO-" el recorrido.
# │ Orden de lectura = orden en que viaja la consulta del cliente.
# │
# │ 1 · ENTRADA      SEG-1.1 Compuerta de frases de control   main._triage
# │                  SEG-1.2 Sanitizador                      prompt_loader.sanitize
# │                  SEG-1.3 Recorte de largo                 prompt_loader.MAX_CONSULTA_CHARS
# │                  SEG-1.4 Quitar tags del delimitador      prompt_loader.DELIMITER_TAG
# │                  SEG-1.5 Enmascarar PII                   prompt_loader.EMAIL / CARD
# │                  SEG-1.6 Moderación de contenido          moderation.moderate, guardrails.decide
# │                  SEG-1.7 Rate limiting (FALTA)            main.triage
# │ 2 · PROMPT       SEG-2.1 Consulta entre delimitadores     prompt_loader.render → triage_v4.yaml
# │                  SEG-2.2 Regla R7 (bloque Seguridad)      prompt_loader.render → triage_v4.yaml
# │                  SEG-2.3 Armado del prompt                prompt_loader.render
# │ 3 · INFERENCIA   SEG-3.1 Roles system / user              llm_client.ask_tool_openai / _gemini
# │                  SEG-3.2 Tool calling forzado             llm_client.TOOL_SCHEMA
# │                  SEG-3.3 Timeout, reintentos y fallback   llm_client.ask_tool, is_transient
# │ 4 · VALIDACIÓN   SEG-4.1 Contrato Pydantic                main._triage, schemas.TriageResponse
# │                  SEG-4.2 Reparación sin eco de salida     main._triage, guardrails.error_summary
# │ 5 · COMPUERTA    SEG-5.1 Enganche en el flujo             main._triage
# │                  SEG-5.2 Promesas prohibidas              guardrails.PROMISE
# │                  SEG-5.3 Eco de frases de control         guardrails.CONTROL
# │                  SEG-5.4 Fuga literal del system          guardrails.leaks_system
# │                  SEG-5.5 Orden de los chequeos            guardrails.check_output
# │                  SEG-5.6 Respuesta de reemplazo           guardrails.safe_response
# │                  SEG-5.7 PII en salida / fuga por traducción (FALTA)  guardrails.check_output
# │ 6 · TRANSVERSAL  SEG-6.1 Suite adversarial                eval.evaluate
# │                  SEG-6.2 Auditoría de bloqueos            main._log, metrics.log_event
# │                  SEG-6.3 Hash de entrada con sal          metrics.input_hash
# │                  SEG-6.4 Retención según severidad        metrics.retention_tag
# │
# │ FLUJO-1 triage() punto de entrada · FLUJO-2 _triage() orquestador
# │ FLUJO-3 load_prompt() versiones · FLUJO-4 eval.main() corrida de evaluación
# └──────────────────────────────────────────────────────────────────────────────
import sys
import os
import time
import uuid
from dotenv import load_dotenv
from pydantic import ValidationError
from .llm_client import ask_tool
from .prompt_loader import load_prompt, render, sanitize
from .schemas import ToolResponse, TriageResponse
from .guardrails import CONTROL, check_output, error_summary, safe_response
from .moderation import THRESHOLDS, moderate
from .metrics import cost_usd, input_hash, log_event, now_iso, retention_tag

load_dotenv()
class TriageError(Exception):
    pass

# ┌─ FLUJO-1 · Punto de entrada público: triage() ───────────────────────────────
# │ Qué:     la única puerta al sistema. La usan la CLI (main) y la evaluación (eval).
# │ Cómo:    delega todo el pipeline en _triage() y, pase lo que pase (respuesta,
# │          bloqueo o excepción), escribe una línea de auditoría en el finally.
# │ Ver:     FLUJO-2 (pipeline) · SEG-6.2 (auditoría)
# │ Claves:  triage, request_id, surface, info
# ├─ SEG-1.7 · ENTRADA · Rate limiting ── ESTADO: FALTA ───────────────────────────
# │ Iría acá, al inicio de triage(), o en la API que la exponga. En una CLI pesa
# │ poco; pasa a obligatorio en cuanto haya un endpoint público.
# └──────────────────────────────────────────────────────────────────────────────
def triage(
    query: str, version: str | None = None, surface: str = "cli", info: dict | None = None
) -> tuple[TriageResponse, list[ToolResponse]]:
    """
        Llama al LLM con el system prompt, user prompt y la query del ticket.
        version: archivo de prompts/ (sin extensión); por defecto PROMPT_VERSION.
        surface: "cli" | "eval", solo para el log. info: dict opcional donde queda el request_id.
        Devuelve la respuesta validada y un ToolResponse por intento (tokens, proveedor, modelo).
        Cada ejecución escribe una línea en data/metrics.jsonl (sin texto del ticket ni de la respuesta).
    """
    info = {} if info is None else info
    info.update(request_id=str(uuid.uuid4()), prompt_version=None, input_gate=None,
                moderation=None, output_gate=None, calls=[])
    t0 = time.perf_counter()
    try:
        return _triage(query, version, info)
    except Exception as e:
        info["error"] = type(e).__name__  # class name only, never the message
        raise
    finally:
        try:
            _log(query, surface, info, time.perf_counter() - t0)
        except Exception as e:  # a logging failure must not replace the real result or error
            print(f"No se pudo escribir la métrica: {type(e).__name__}", file=sys.stderr)

# ┌─ SEG-6.2 · TRANSVERSAL · Auditoría de bloqueos ──────────────────────────────
# │ Qué:     una línea por ejecución en data/metrics.jsonl con qué compuerta actuó
# │          (input_gate, moderation, output_gate), versión de prompt y de umbrales,
# │          proveedor, modelo, tokens, costo y latencia.
# │ Por qué: poder reconstruir cada bloqueo sin guardar el texto del cliente ni la
# │          respuesta del modelo: solo un hash (SEG-6.3) y la clase del error.
# │ Ver:     SEG-6.3 (input_hash) · SEG-6.4 (retention_tag) · metrics.log_event
# │ Claves:  auditoría, log, metrics.jsonl, input_gate, output_gate
# └──────────────────────────────────────────────────────────────────────────────
def _log(query: str, surface: str, info: dict, latency: float) -> None:
    calls, error = info["calls"], info.get("error")
    last = calls[-1] if calls else None
    costs = [cost_usd(c.model, c.input_tokens, c.output_tokens) for c in calls]
    tin, tout = sum(c.input_tokens for c in calls), sum(c.output_tokens for c in calls)
    log_event({
        "ts": now_iso(),
        "request_id": info["request_id"],
        "surface": surface,
        "prompt_version": info["prompt_version"],
        "thresholds_version": THRESHOLDS["version"],
        "provider": last.provider if last else None,
        "model": last.model if last else None,
        "attempts": len(calls),
        "input_tokens": tin,
        "output_tokens": tout,
        "total_tokens": tin + tout,
        "latency_s": round(latency, 3),
        "cost_usd": sum(costs) if costs and None not in costs else None,
        "input_gate": info["input_gate"],
        "moderation": info["moderation"],
        "output_gate": info["output_gate"],
        "input_hash": input_hash(query),
        "retention_tag": retention_tag(info["input_gate"], info["moderation"], info["output_gate"], error),
        "error": error,
    })

# ┌─ FLUJO-2 · Orquestador del pipeline: _triage() ──────────────────────────────
# │ Recorrido de la consulta, en este orden:
# │   1 Entrada     SEG-1.1 frases de control → SEG-1.6 moderación
# │   2 Prompt      render(): SEG-1.2..1.5 sanitiza y SEG-2.x arma system/user
# │   3 Inferencia  ask_tool(): SEG-3.x
# │   4 Validación  SEG-4.1 contrato → si falla, SEG-4.2 reparación y reintento
# │   5 Compuerta   SEG-5.1 check_output → safe_response si bloquea
# │ Las dos compuertas (1 y 5) terminan en la misma safe_response() (SEG-5.6).
# │ Claves:  pipeline, orquestador, flujo, etapas
# └──────────────────────────────────────────────────────────────────────────────
def _triage(query: str, version: str | None, info: dict) -> tuple[TriageResponse, list[ToolResponse]]:
    prompt = load_prompt(version or os.getenv("PROMPT_VERSION", "triage_v4"))
    info["prompt_version"] = prompt["version"]
    # ┌─ SEG-1.1 · ENTRADA · Compuerta de frases de control ───────────────────────
    # │ Qué:     si la consulta original trae una frase de control ("olvidá las
    # │          instrucciones", "modo debug", "SYSTEM:") se corta acá.
    # │ Por qué: es un intento de inyección. No se llama al LLM, no se gasta una
    # │          llamada y el modelo no tiene chance de obedecer.
    # │ Sale:    safe_response("intento-de-inyeccion") → revisión humana. La lista de
    # │          llamadas vuelve vacía porque no hubo inferencia.
    # │ Nota:    se DETECTA, no se reescribe: reescribir bajó v4 a 6/10 (ver SEG-1.2).
    # │ Ver:     SEG-5.3 (misma regex CONTROL en la salida) · SEG-5.6
    # │ Claves:  inyección, prompt injection, CONTROL, input_gate
    # └────────────────────────────────────────────────────────────────────────────
    if CONTROL.search(query):
        info["input_gate"] = "intento-de-inyeccion"
        print("Entrada bloqueada por la compuerta: intento-de-inyeccion", file=sys.stderr)
        return safe_response("intento-de-inyeccion"), []
    # ┌─ SEG-1.6 · ENTRADA · Moderación de contenido ──────────────────────────────
    # │ Qué:     clasifica la consulta ya sanitizada (sin PII) con OpenAI Moderation
    # │          y la ubica en una banda por categoría: allow / flag / block.
    # │ Sale:    block → safe_response("moderacion: ...") sin llamar al LLM.
    # │          flag  → sigue, pero al final se agrega "Revisión humana" a actions.
    # │ Umbrales: config/moderation.yaml (versionado, se registra en el log).
    # │ Ver:     moderation.moderate (fail-closed) · guardrails.decide
    # │ Claves:  moderación, moderation, umbrales, thresholds, flag, block
    # └────────────────────────────────────────────────────────────────────────────
    action, reasons, severity = moderate(sanitize(query))
    info["moderation"] = {"action": action, "severity": severity, "reasons": reasons}
    codes = ",".join(r["code"] for r in reasons)
    if action == "block":
        print(f"Entrada bloqueada por moderación: {codes}", file=sys.stderr)
        return safe_response("moderacion: " + codes), []
    # Etapa 2 · Prompt: render() sanitiza (SEG-1.2..1.5) y arma system/user (SEG-2.x).
    system, base_user = render(prompt, query)
    # Capa semántica: solo se reintenta cuando la respuesta no cumple el contrato (SEG-4.2).
    max_attempts = int(os.getenv("MAX_REPAIR_ATTEMPTS", 2))
    user = base_user
    calls: list[ToolResponse] = info["calls"]

    if max_attempts < 1:
        raise ValueError("MAX_REPAIR_ATTEMPTS debe ser al menos 1.")

    for attempt in range(max_attempts):
        # Etapa 3 · Inferencia: ver SEG-3.1..3.3 en llm_client.py.
        response = ask_tool(
            system, user, prompt.get("temperature", 0), prompt.get("max_output_tokens", 300)
        )
        calls.append(response)
        try:
            # ┌─ SEG-4.1 · VALIDACIÓN · Contrato Pydantic ─────────────────────────────
            # │ Qué:     la tool call garantiza la forma básica; Pydantic exige el
            # │          contrato completo: categoría cerrada, confianza entre 0 y 1,
            # │          answer no vacío. Args vacíos o truncados también fallan acá.
            # │ Si falla: salta al except → SEG-4.2 (reparación).
            # │ Ver:     schemas.TriageResponse · SEG-3.2
            # │ Claves:  validación, contrato, schema, Pydantic, model_validate
            # └────────────────────────────────────────────────────────────────────────
            if response.args is None:
                raise ValueError("Los argumentos de la tool call llegaron vacíos o truncados.")


            result = TriageResponse.model_validate(response.args)
            # ┌─ SEG-5.1 · COMPUERTA · Enganche en el flujo ───────────────────────────
            # │ Qué:     revisa lo que escribió el modelo justo después de validarlo.
            # │          Si check_output() devuelve un motivo, la salida se descarta
            # │          entera y se reemplaza por safe_response(motivo).
            # │ Ver:     SEG-5.2..5.5 (chequeos) · SEG-5.6 (reemplazo)
            # │ Claves:  compuerta de salida, output gate, check_output, bloqueo
            # └────────────────────────────────────────────────────────────────────────
            reason = check_output(result, system)
            if reason:
                info["output_gate"] = reason
                print(f"Salida bloqueada por la compuerta: {reason}", file=sys.stderr)
                result = safe_response(reason)
            if action == "flag":
                # SEG-1.6 (flag): se agrega después de la compuerta; es texto nuestro, no del modelo.
                result.actions.append(f"Revisión humana: contenido dudoso ({codes})")
            return result, calls

        except (ValidationError, ValueError) as e:
            # ┌─ SEG-4.2 · VALIDACIÓN · Reparación sin eco de salida ───────────────────
            # │ Qué:     reintenta con el mismo prompt + un resumen del error.
            # │ Por qué: al modelo solo vuelven nombres de campo y reglas violadas.
            # │          Su salida rechazada nunca entra al prompt ni al log sin haber
            # │          pasado por la compuerta de salida (podría traer una inyección).
            # │ Límite:  MAX_REPAIR_ATTEMPTS (default 2); agotado → TriageError.
            # │ Test:    python -m src.test_repair
            # │ Ver:     guardrails.error_summary
            # │ Claves:  reparación, repair, reintento, error_summary
            # └────────────────────────────────────────────────────────────────────────
            err = error_summary(e)
            user = (
                f"{base_user}\n\n"
                f"Tu respuesta anterior no pasó la validación:\n{err}\n\n"
                "Llama la herramienta de nuevo con argumentos corregidos."
            )
            print(f"Error en el intento {attempt + 1}: {err}", file=sys.stderr)
    raise TriageError(
        f"Se alcanzó el número máximo de intentos ({max_attempts}) sin obtener una respuesta válida."
    )
    
def main() -> None:
    # Windows redirects stdout as cp1252; keep the JSON readable UTF-8.
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    info: dict = {}
    try:
        response, _ = triage(sys.argv[1], info=info)
    except Exception as e:
        # Metrics are already logged in triage()'s finally; just fail cleanly, no traceback.
        print(f"Error: {type(e).__name__}: {e}", file=sys.stderr)
        print(f"request_id: {info.get('request_id')}", file=sys.stderr)
        sys.exit(1)
    print(f"request_id: {info['request_id']}", file=sys.stderr)
    print(response.model_dump_json(indent=2))

if __name__ == "__main__":
    if len(sys.argv) < 2 or not sys.argv[1].strip():
        print('Uso: python -m src.main "<consulta>"', file=sys.stderr)
        sys.exit(1)
    main()