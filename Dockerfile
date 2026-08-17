# Build context is the STACK ROOT, not this repository:
#
#     docker build -f MetaGate/Dockerfile .
#
# The image installs the canonical protocol package from the sibling LegiVellum
# checkout. `legivellum` is a hard dependency and is not published to an index,
# so a repo-scoped context cannot satisfy it -- the build fails with
# "No matching distribution found for legivellum" rather than silently
# producing an image that cannot validate receipts.

# MetaGate Dockerfile
# Bootstrap authority for LegiVellum-compatible systems

FROM python:3.12-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src

# Set work directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for caching
# The canonical protocol package first: receipt models, validation, and the
# schema, which ships as package data so validation needs no source checkout.
COPY LegiVellum/pyproject.toml LegiVellum/README.md /src/LegiVellum/
COPY LegiVellum/shared/ /src/LegiVellum/shared/
RUN pip install --no-cache-dir /src/LegiVellum

COPY MetaGate/requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY MetaGate/src/ ./src/
COPY MetaGate/migrations/ ./migrations/

# Create non-root user
RUN adduser --disabled-password --gecos "" metagate && \
    chown -R metagate:metagate /app
USER metagate

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import json, os, urllib.request; url=os.environ.get('METAGATE_MCP_URL','http://localhost:8000/mcp'); token=os.environ.get('METAGATE_API_KEY'); payload={'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':'metagate.health','arguments':{}}}; req=urllib.request.Request(url, data=json.dumps(payload).encode(), headers={'Content-Type':'application/json'}); token and req.add_header('Authorization','Bearer '+token); resp=urllib.request.urlopen(req, timeout=5); data=json.load(resp); assert 'result' in data"

# Run the application
CMD ["uvicorn", "metagate.main:app", "--host", "0.0.0.0", "--port", "8000"]
