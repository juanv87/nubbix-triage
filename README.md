# Nubbix Support Triage

Asistente de triage de tickets de soporte (nivel 1) para Nubbix, un SaaS de gestión para pymes en Latinoamérica. Recibe el texto de un ticket y devuelve un JSON con respuesta sugerida, categoría, confianza y acciones para el agente humano.

## Objetivo final

Un asistente que ayude al agente de soporte (no que lo reemplace): clasifica el ticket, redacta una respuesta y sugiere acciones, con salida estructurada y evaluable para comparar versiones de prompt y proveedores.

## Uso

```bash
# 1. Entorno virtual e instalación
python -m venv .venv
.venv\Scripts\activate          # Windows (Linux/macOS: source .venv/bin/activate)
pip install -r requirements.txt

# 2. Configuración
cp .env.example .env            # completar las API keys

# 3. Ejecutar (desde la raíz del repo; los imports relativos requieren -m)
python -m src.main "Me cobraron dos veces la suscripción de este mes"
```

Salida: el `TriageResponse` ya validado, en JSON:

```json
{
  "answer": "...",
  "confidence": 0.95,
  "category": "billing",
  "actions": ["..."]
}
```

Categorías: `billing`, `technical`, `account`, `other` (definidas en `CATEGORIES`, en `src/schemas.py`).

### Variables de entorno

| Variable | Default | Descripción |
|---|---|---|
| `OPENAI_API_KEY` | — | Key de OpenAI (la lee el SDK) |
| `GEMINI_API_KEY` | — | Key de Gemini |
| `LLM_PROVIDER` | `openai` | Proveedor principal (`openai` \| `gemini`) |
| `LLM_FALLBACK_PROVIDER` | `gemini` | Proveedor de respaldo si el principal falla con un error transitorio (red, timeout, 408/409/429, 5xx) |
| `OPENAI_MODEL` | `gpt-4o-mini` | Modelo de OpenAI |
| `GEMINI_MODEL` | `gemini-3.5-flash` | Modelo de Gemini |
| `LLM_TIMEOUT` | `20` | Timeout por request, en segundos |
| `LLM_HTTP_MAX_RETRIES` | `2` | Reintentos del SDK ante errores transitorios (sin contar el intento inicial) |
| `MAX_REPAIR_ATTEMPTS` | `2` | Intentos totales cuando la tool call no valida contra el esquema o llega vacía/truncada |
| `MODERATION_PROVIDER` | `openai` | Moderación de la entrada (`openai` \| `mock` \| `off`). Si el clasificador falla, el ticket se marca `flag` (fail-closed), nunca se permite |
| `PROMPT_VERSION` | `triage_v4` | Versión de prompt a usar (archivo de `prompts/` sin extensión). `triage_v4` es la elegida por datos; ver `prompts/CHANGELOG.md` |

`temperature` y `max_output_tokens` son opcionales en el YAML de cada prompt (por defecto `0` y `300`).

### Prompts versionados

Cada prompt es `prompts/triage_vN.yaml` con los campos `version` (igual al nombre del archivo), `fecha`, `tecnica` (zero-shot, few-shot, ...), `descripcion`, `system` y `user`. Los placeholders `{consulta}`, `{empresa}` y `{categorias}` se rellenan desde el código; las llaves literales se escriben `{{ }}`. Un prompt nunca se edita: cada cambio es un archivo nuevo y una fila en `prompts/CHANGELOG.md`.

## Estructura de directorios

```
.
├── data/
│   ├── tickets.jsonl          # 34 tickets etiquetados (20 dev, 14 test) con reglas R1-R9
│   └── adversarial.jsonl      # 10 casos de prompt injection
├── prompts/
│   ├── CHANGELOG.md           # Historia de versiones de prompts
│   ├── triage_v1.yaml         # Línea base zero-shot mínima
│   ├── triage_v2.yaml         # v1 + 3 ejemplos few-shot
│   ├── triage_v3.yaml         # v2 + 1 ejemplo sacado de un error real (NX-007)
│   ├── triage_v4.yaml         # v2 + seguridad (delimitadores, consulta como dato)
│   └── triage_v5.yaml         # v4 + R7 explícita y ejemplo 3 sin prometer reintegro
├── resultados/                # Una corrida de eval por archivo .jsonl + dashboard.html
├── src/
│   ├── main.py                # CLI y triage(): validación y ciclo de reparación
│   ├── llm_client.py          # Clientes OpenAI/Gemini, tool calling, fallback entre proveedores
│   ├── schemas.py             # Contratos Pydantic: TriageResponse, ToolResponse, CATEGORIES
│   ├── prompt_loader.py       # Carga y valida prompts YAML; render() con guard de delimitadores
│   ├── eval.py                # Runner de evaluación por versión, categoría y regla
│   ├── dashboard.py           # Genera resultados/dashboard.html
│   └── dashboard_template.html
├── .env.example               # Plantilla de configuración
└── requirements.txt           # Dependencias fijadas
```

## Cómo funciona

1. `main.py` recibe la consulta por argumento.
2. `load_prompt(PROMPT_VERSION)` carga y valida el YAML; `render` inyecta ticket, empresa y categorías en `system`/`user`. Antes, `sanitize` quita del texto del cliente las etiquetas `<consulta>`, para que no pueda cerrar el delimitador y escribir fuera de él.
3. `ask_tool` fuerza una tool call (`clasificar_consulta`) cuyo schema sale de `TriageResponse.model_json_schema()`: el contrato Pydantic es la única fuente de verdad. Cada proveedor entrega los argumentos distinto (OpenAI como string JSON, Gemini como dict); `ask_tool` los normaliza en `ToolResponse.args` (`None` si el JSON llegó truncado).
4. `triage()` valida `args` con `TriageResponse.model_validate`. Los reintentos tienen tres capas:
   1. **Transporte (SDK):** errores transitorios con backoff exponencial (`LLM_HTTP_MAX_RETRIES`).
   2. **Fallback:** si el principal agota sus reintentos con un error transitorio, prueba el de respaldo. Los errores de configuración (400/401/403/404) se propagan.
   3. **Semántica:** si los args no validan o llegan vacíos, se reintenta con un prompt de reparación (`MAX_REPAIR_ATTEMPTS`).
5. El prompt trata el ticket como dato no confiable (defensa básica contra prompt injection, medida con el split `adversarial`).

## Evaluación

```bash
python -m src.eval                                   # todas las versiones, split dev
python -m src.eval --versiones triage_v1 triage_v2   # solo algunas
python -m src.eval --split test                      # comparación final, una sola vez
python -m src.eval --split adversarial               # suite de prompt injection (imprime cada answer)
```

| Split | Para qué |
|---|---|
| `dev` (default) | Iterar sobre los prompts mirando los fallos |
| `test` | Comparación final; no se usa para iterar, así no se contamina |
| `all` | dev + test juntos; vista general, no para decidir |
| `adversarial` | Resistencia a prompt injection (`data/adversarial.jsonl`) |

Corre cada ticket con el mismo `triage()` de la app e imprime accuracy por categoría y por regla de etiquetado, tokens, latencia e intentos de reparación. Los errores de API (cuota, red) se cuentan aparte y no afectan el accuracy. El detalle por caso queda en `resultados/<fecha>_<split>.jsonl`. Cada caso es una llamada real al LLM.

`python -m src.dashboard` arma `resultados/dashboard.html` con todas esas corridas (precisión por split y por regla, tickets fallados, respuestas ante injection, costo y estabilidad entre corridas). Es un archivo estático: se abre directo en el navegador.

## Plan

- [x] Prompt zero-shot v1 con contrato de salida JSON
- [x] Cliente multi-proveedor (OpenAI + Gemini) con fallback
- [x] Prompts versionados en YAML
- [x] Validar la salida con Pydantic (esquema, categorías válidas, rango de `confidence`) y reparación
- [x] Dataset de tickets etiquetados y script de evaluación
- [x] Prompts v2-v5 (few-shot, error real, seguridad) y comparación entre versiones
- [x] Suite adversarial y dashboard de resultados
- [x] Salida estructurada por tool calling, con schema generado desde el contrato
- [x] Selección de prompt por variable de entorno (`PROMPT_VERSION`)
- [ ] Tests automatizados
- [ ] Selección de versión/técnica como argumento del comando

## Estado actual

Pipeline completo: prompt `triage_v4` por defecto, salida por tool calling validada con Pydantic, fallback entre proveedores y evaluación sobre dev/test/adversarial con dashboard. La migración a tool calling se re-evaluó con `gpt-4o-mini` sin regresiones (dev 18/20 y adversarial 9/10, igual que con JSON mode). Faltan tests automatizados.
