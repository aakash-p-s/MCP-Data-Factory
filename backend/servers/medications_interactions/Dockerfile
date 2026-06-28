FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .

ENV MEDS_PORT=8003
EXPOSE 8003

# Serves FHIR MedicationStatement + interaction analysis over MCP Streamable HTTP at /mcp
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8003"]
