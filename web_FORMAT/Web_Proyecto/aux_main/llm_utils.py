from openai import OpenAI, APIConnectionError
from fastapi import HTTPException

LLM_URL = "http://host.docker.internal:8001/v1"
LLM_API_KEY = "local-token"


def get_llm_client():
    return OpenAI(
        base_url=LLM_URL,
        api_key=LLM_API_KEY,
        timeout=60.0
    )


def check_llm_available() -> bool:
    try:
        client = get_llm_client()

        # Cualquier llamada sencilla sirve
        client.models.list()

        return True

    except Exception as e:
            print(type(e))
            print(repr(e))
            
            return False

    except APIConnectionError as e:
        print(e.__cause__)
    

def require_llm():
    if not check_llm_available():
        raise HTTPException(
            status_code=503,
            detail="El servicio de IA no está disponible en este momento."
        )