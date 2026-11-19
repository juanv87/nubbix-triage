import yaml
from pathlib import Path

def load_prompt(prompt_name):
    """
    Load a prompt template from a YAML file.

    Args:
        prompt_name (str): The name of the prompt template to load.

    Returns:
        dict: The loaded prompt template.
    """
    with open(Path(__file__).parent.parent / "prompts" / f"{prompt_name}.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)

if __name__ == "__main__":
    # Ejemplo de uso
    # Este bloque solo corre al ejecutar el archivo directamente
    # (python -m src.prompt_loader), no cuando otro módulo lo importa.
    # Sirve como prueba manual: verifica que el YAML carga y que el template
    # se rellena bien, sin llamar a ningún LLM. La query está hardcodeada a
    # propósito; en main.py la query real viene de sys.argv[1].
    prompt = load_prompt("v1_zero_shot")["user_template"].format(query="Hola, me cobraron dos veces la suscripción de este mes, necesito que me reintegren uno de los cargos.")
    print(prompt)