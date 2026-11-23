from typing import Literal
from pydantic import BaseModel, Field, ValidationError

# Single source of truth: the schema validates these keys and prompts inject them via {categorias}.
CATEGORIES = {
    "billing": "cobros, facturas, pagos a Nubbix, reintegros, precio de la suscripción.",
    "technical": "errores, fallas, caídas del servicio, integraciones que fallan, lentitud.",
    "account": "usuarios, permisos, inicio de sesión, contraseña, email de administrador, configuración de la cuenta.",
    "other": "todo lo demás (consultas comerciales, planes, descuentos, comentarios).",
}

class TriageResponse(BaseModel):
    answer: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)
    category: Literal[tuple(CATEGORIES)]
    actions: list[str]

class ToolResponse(BaseModel):
    # args is None when the provider's arguments could not be parsed (e.g. truncated JSON).
    args: dict | None
    provider: Literal["openai", "gemini"]
    model: str
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)

if __name__ == "__main__":
    # Ejemplo de uso
    example_response = TriageResponse(
        answer="El problema está relacionado con la facturación.",
        confidence=0.95,
        category="billing",
        actions=["Revisar factura", "Contactar soporte"]
    )
    # Caso que no cumple con las validaciones (confidence fuera de rango)
    try:
        invalid_response = TriageResponse(
            answer="Hay un error de tipografía en la factura.",
            confidence=1.5,
            category="Facturación",
            actions=[]
        )
    except ValidationError as e:
        print(f"Error de validación: {e}")

    # Otro caso que no cumple con las validaciones (confidence fuera de rango)
    try:
        invalid_response_2 = TriageResponse(
            answer="El usuario no puede acceder a su cuenta.",
            confidence=-0.1,
            category="technical",
            actions=["Reiniciar contraseña"]
        )
    except ValidationError as e:
        print(f"Error de validación: {e}")
    
    print(example_response.model_dump_json(indent=2))