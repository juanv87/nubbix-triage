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

# 3. Ejecutar (desde la raíz del repo)
python -m src.main "Me cobraron dos veces la suscripción de este mes"
```

Salida (dict de Python impreso en consola):

```python
{"text": "<JSON del modelo>", "provider": "openai", "model": "gpt-4o-mini",
 "input_tokens": 0, "output_tokens": 0}
```

`text` contiene el JSON del contrato definido en el prompt:

```json
{"answer": "...", "confidence": 0.95, "category": "billing", "actions": ["..."]}
```

Categorías: `billing`, `technical`, `account`, `other`.

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
| `MAX_REPAIR_ATTEMPTS` | `2` | Intentos totales cuando la respuesta no valida contra el esquema |
| `PROMPT_VERSION` | `triage_v1` | Versión de prompt a usar (archivo de `prompts/` sin extensión) |

`temperature` y `max_output_tokens` son opcionales en el YAML de cada prompt (por defecto `0` y `300`).

### Prompts versionados

Cada prompt es `prompts/triage_vN.yaml` con los campos `version` (igual al nombre del archivo), `fecha`, `tecnica` (zero-shot, few-shot, ...), `descripcion`, `system` y `user`. Los placeholders `{consulta}`, `{empresa}` y `{categorias}` se rellenan desde el código; las llaves literales se escriben `{{ }}`. Un prompt nunca se edita: cada cambio es un archivo nuevo y una fila en `prompts/CHANGELOG.md`.

## Estructura de directorios

```
.
├── prompts/
│   ├── CHANGELOG.md        # Historia de versiones de prompts
│   ├── triage_v1.yaml      # Línea base zero-shot mínima
│   └── triage_v2.yaml      # v1 + 3 ejemplos few-shot
├── src/
│   ├── main.py             # CLI, clientes de OpenAI/Gemini, fallback entre proveedores
│   └── prompt_loader.py    # Carga prompts YAML desde prompts/
├── .env.example            # Plantilla de configuración
└── requirements.txt        # Dependencias fijadas
```

## Cómo funciona

1. `main.py` recibe la consulta por argumento.
2. `load_prompt(PROMPT_VERSION)` carga y valida el YAML; `render` inyecta ticket, empresa y categorías en `system`/`user`.
3. `call_llm` llama al proveedor principal con JSON forzado y los parámetros del YAML. Los reintentos tienen tres capas:
   1. **Transporte (SDK):** errores transitorios con backoff exponencial (`LLM_HTTP_MAX_RETRIES`).
   2. **Fallback:** si el principal agota sus reintentos con un error transitorio, prueba el de respaldo. Los errores de configuración (400/401/403/404) se propagan.
   3. **Semántica:** si el JSON no valida, se reintenta con un prompt de reparación (`MAX_REPAIR_ATTEMPTS`).
4. El prompt trata el ticket como dato no confiable (defensa básica contra prompt injection).

## Evaluación

```bash
python -m src.eval                                   # todas las versiones, split dev
python -m src.eval --versiones triage_v1 triage_v2   # solo algunas
python -m src.eval --split test                      # comparación final, una sola vez
```

Corre cada ticket de `data/tickets.jsonl` con el mismo `triage()` de la app e imprime accuracy por categoría y por regla de etiquetado, tokens, latencia e intentos de reparación. El detalle por caso queda en `resultados/<fecha>_<split>.jsonl`. Cada caso es una llamada real al LLM.

## Plan

- [x] Prompt zero-shot v1 con contrato de salida JSON
- [x] Cliente multi-proveedor (OpenAI + Gemini) con fallback
- [x] Prompts versionados en YAML
- [ ] Validar/parsear el JSON de salida (esquema, categorías válidas, rango de `confidence`)
- [ ] Dataset de tickets de prueba y script de evaluación
- [ ] Prompt v2 (few-shot) y comparación contra v1
- [ ] Tests automatizados
- [x] Selección de prompt por variable de entorno (`PROMPT_VERSION`)
- [ ] Selección de versión/técnica como argumento del comando

## Estado actual

Prototipo funcional de punta a punta con prompt v1. Sin validación de la salida, sin evaluación y sin tests. Este README se actualiza a medida que avanza el proyecto.
