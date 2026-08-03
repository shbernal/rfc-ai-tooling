# The HTTP mode, packaged. Nobody operates a public instance of this — the
# image exists so that anyone who wants one can deploy their own.
#
#   docker build -t mcp-server-rfc mcp/
#   docker run --rm -p 8080:8080 mcp-server-rfc
#
# Build context is mcp/, not the repository root.
FROM python:3.13-slim

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .

# An ephemeral mirror. It never holds the full corpus — that needs rsync and
# 512 MB, and this image has neither — but caching fetched documents for the
# life of the instance keeps a public deployment from re-fetching the same RFC
# from the RFC Editor on every call.
ENV RFC_MIRROR=/tmp/rfc-mirror \
    RFC_TRANSPORT=http \
    HOST=0.0.0.0 \
    PORT=8080 \
    PYTHONDONTWRITEBYTECODE=1 \
    # Without this the logs sit in a buffer and `docker logs` is empty on a
    # server that is answering requests normally.
    PYTHONUNBUFFERED=1

EXPOSE 8080
USER nobody
CMD ["mcp-server-rfc"]
