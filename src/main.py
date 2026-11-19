import sys

from .llm_client import call_llm
from .prompt_loader import load_prompt


def main() -> int:
    if len(sys.argv) < 2 or not sys.argv[1].strip():
        print('Uso: python -m src.main "<consulta>"', file=sys.stderr)
        return 2
    
    prompt = load_prompt("v1_zero_shot")
    user = prompt["user_template"].format(query=sys.argv[1])
    response_content = call_llm(prompt["system"], user)
    
    print(response_content)
    
    return 0


if __name__ == "__main__":
    sys.exit(main())