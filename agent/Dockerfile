# agent/Dockerfile
# Runtime Agent — LangGraph MCP Host
# Python 3.12-slim (PRD §8 requires 3.12 or 3.13)

FROM python:3.12-slim

WORKDIR /app

# Install dependencies first (layer-cached)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy agent source
COPY . .

# Expose the /ask endpoint
EXPOSE 8500

CMD ["uvicorn", "runtime_agent:app", "--host", "0.0.0.0", "--port", "8500"]
