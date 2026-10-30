# The HTTP mode, packaged. Nobody operates a public instance of this — the
# image exists so that anyone who wants one can deploy their own.
#
#   docker build -t mcp-server-rfc mcp/
#   docker run --rm -p 8080:8080 mcp-server-rfc
#
# Over stdio, with full-text search, the mirror goes in a named volume:
#
#   docker run --rm -it -v rfc-mirror:/mirror mcp-server-rfc mcp-server-rfc sync --index
#   docker run --rm -i -v rfc-mirror:/mirror -e RFC_TRANSPORT=stdio mcp-server-rfc
#
# Build context is mcp/, not the repository root.
FROM python:3.13-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends rsync \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .

# Owned by nobody here because an empty named volume takes this directory's
# ownership on first mount, which is what lets `sync` write to it. With no
# volume it lasts as long as the container, and still keeps a public deployment
# from re-fetching the same RFC from the RFC Editor on every call.
RUN mkdir /mirror && chown nobody /mirror

ENV RFC_MIRROR=/mirror \
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
