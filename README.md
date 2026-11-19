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
| `LLM_FALLBACK_PROVIDER` | `gemini` | Proveedor de respaldo si el principal falla con error de API |
| `OPENAI_MODEL` | `gpt-4o-mini` | Modelo de OpenAI |
| `GEMINI_MODEL` | `gemini-3.5-flash` | Modelo de Gemini |

## Estructura de directorios

```
.
├── prompts/
│   └── v1_zero_shot.yaml   # Prompt versionado (system + user_template)
├── src/
│   ├── main.py             # CLI, clientes de OpenAI/Gemini, fallback entre proveedores
│   └── prompt_loader.py    # Carga prompts YAML desde prompts/
├── .env.example            # Plantilla de configuración
└── requirements.txt        # Dependencias fijadas
```

## Cómo funciona

1. `main.py` recibe la consulta por argumento.
2. `load_prompt("v1_zero_shot")` carga el YAML y se inyecta el ticket en `user_template`.
3. `call_llm` llama al proveedor principal (temperatura 0, JSON forzado, máx. 300 tokens, timeout 20 s, con reintentos). Si falla con error de API, prueba el de respaldo.
4. El prompt trata el ticket como dato no confiable (defensa básica contra prompt injection).

## Plan

- [x] Prompt zero-shot v1 con contrato de salida JSON
- [x] Cliente multi-proveedor (OpenAI + Gemini) con fallback
- [x] Prompts versionados en YAML
- [ ] Validar/parsear el JSON de salida (esquema, categorías válidas, rango de `confidence`)
- [ ] Dataset de tickets de prueba y script de evaluación
- [ ] Prompt v2 (few-shot) y comparación contra v1
- [ ] Tests automatizados
- [ ] Selección de prompt por CLI/variable de entorno (hoy está fijo en `v1_zero_shot`)

## Estado actual

Prototipo funcional de punta a punta con prompt v1. Sin validación de la salida, sin evaluación y sin tests. Este README se actualiza a medida que avanza el proyecto.
