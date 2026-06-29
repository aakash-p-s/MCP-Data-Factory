# import os
# from dotenv import load_dotenv
# from openai import OpenAI

# # Load .env file
# load_dotenv()

# # Read API key
# api_key = os.getenv("OPENAI_API_KEY")

# client = OpenAI(api_key=api_key)

# try:
#     response = client.models.list()

#     print("✅ API Key is working")

#     for model in response.data:
#         print(model.id)

# except Exception as e:
#     print("❌ Error:")
#     print(e)
"""
llm_config.py
─────────────────────────────────────────────────────
Shared OpenAI LLM instances.  ALL agents import from here.
No agent may instantiate its own LLM.
"""
import os
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

load_dotenv()

_api_key = os.getenv("OPENAI_API_KEY")
if not _api_key:
    raise EnvironmentError(
        "OPENAI_API_KEY is not set. "
        "Copy .env.example → .env and add your key."
    )

# Primary LLM — used by data_quality, log_analysis, rca, recommendation agents
llm = ChatOpenAI(
    model="gpt-4",
    temperature=0.3,
    max_tokens=2048,
    api_key=_api_key,
)

# Fast LLM — used by compliance agent only
llm_fast = ChatOpenAI(
    model="gpt-3.5-turbo",
    temperature=0.3,
    max_tokens=1024,
    api_key=_api_key,
)


def check_llm_connection(prompt: str = "Reply with: CONNECTION OK") -> str:
    """Run a small verification call against the primary LLM."""
    response = llm.invoke(prompt)
    return response.content


if __name__ == "__main__":
    try:
        result = check_llm_connection()
        print(f"LLM connection successful: {result}")
    except Exception as exc:
        print(f"LLM connection failed: {exc}")
