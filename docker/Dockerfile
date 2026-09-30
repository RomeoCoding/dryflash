# syntax=docker/dockerfile:1
# Base image: ESP-IDF v6.1 (toolchains, GDB, stock Espressif QEMU) plus the MCP server.
#
#   docker build -f docker/Dockerfile -t dryflash .                 # runtime image
#   docker build -f docker/Dockerfile --target test -t dryflash:test .
#
# MCP clients run it as: docker run -i --rm -v <project>:/work dryflash
FROM espressif/idf:v6.1@sha256:81893c71bb5e570088901f21def8684c25cd2a9020281bd01b843a7655edb18c AS base

# The server gets its own venv on the system Python 3.12, separate from IDF's venv, so its
# pinned dependencies can never clash with the ones idf.py needs.
ENV UV_PYTHON=/usr/bin/python3.12 \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    DRYFLASH_HOME=/opt/dryflash
RUN python3 -m venv /opt/uv && /opt/uv/bin/pip install --no-cache-dir uv==0.12.20

WORKDIR /opt/dryflash
COPY pyproject.toml uv.lock README.md LICENSE ./
RUN /opt/uv/bin/uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN /opt/uv/bin/uv sync --frozen --no-dev
COPY examples ./examples
COPY docker/entrypoint.sh /usr/local/bin/dryflash-entrypoint
RUN chmod +x /usr/local/bin/dryflash-entrypoint

WORKDIR /work
ENTRYPOINT ["/usr/local/bin/dryflash-entrypoint"]
CMD ["serve"]

FROM base AS test
WORKDIR /opt/dryflash
RUN /opt/uv/bin/uv sync --frozen
COPY tests ./tests
COPY scripts ./scripts
COPY bench ./bench
WORKDIR /opt/dryflash
CMD ["pytest"]
