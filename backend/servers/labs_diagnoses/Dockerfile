FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .

ENV LABS_PORT=8002
EXPOSE 8002

# Serves FHIR Observation/Condition over MCP Streamable HTTP at /mcp
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8002"]
