FROM python:3.12-slim

LABEL maintainer="J. Gravelle <j@gravelle.us>"
LABEL description="jCodeMunch MCP server — token-efficient code intelligence via tree-sitter AST parsing"

# System deps for tree-sitter compilation and git operations
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ git \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN useradd -m -s /bin/bash jcodemunch

# Install jcodemunch-mcp
COPY . /opt/jcodemunch-mcp
RUN pip install --no-cache-dir /opt/jcodemunch-mcp && rm -rf /opt/jcodemunch-mcp

# Index storage volume
RUN mkdir -p /data/code-index && chown jcodemunch:jcodemunch /data/code-index
VOLUME /data/code-index

USER jcodemunch

ENV CODE_INDEX_PATH=/data/code-index
ENV JCODEMUNCH_TRANSPORT=sse
ENV JCODEMUNCH_HOST=0.0.0.0
ENV JCODEMUNCH_PORT=8901
# Set via docker run -e or docker-compose:
# ENV JCODEMUNCH_HTTP_TOKEN=<your-bearer-token>
# ENV JCODEMUNCH_RATE_LIMIT=60

EXPOSE 8901

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
    CMD python -c "import socket; s=socket.create_connection(('localhost',8901),2); s.close()" || exit 1

ENTRYPOINT ["jcodemunch-mcp", "serve"]
