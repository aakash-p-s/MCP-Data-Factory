FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .

ENV VITALS_PORT=8001
EXPOSE 8001

# Stub serves hardcoded FHIR over MCP Streamable HTTP at /mcp
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001"]
