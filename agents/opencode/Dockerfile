FROM node:22-bookworm-slim AS cli
ARG TARGETARCH
RUN set -eu; \
    case "$TARGETARCH" in \
      amd64) package=opencode-linux-x64-baseline ;; \
      arm64) package=opencode-linux-arm64 ;; \
      *) printf 'Unsupported OpenCode architecture: %s\n' "$TARGETARCH" >&2; exit 1 ;; \
    esac; \
    npm install --prefix /opt/cli --no-audit --no-fund --ignore-scripts "$package@1.19.6"; \
    install -m 0755 "/opt/cli/node_modules/$package/bin/opencode" /usr/local/bin/opencode; \
    test "$(opencode --version)" = 1.19.6

FROM python:3.12-slim-bookworm
COPY --from=cli /usr/local/bin/opencode /usr/local/bin/opencode
WORKDIR /app
COPY baseline.py .
USER 10001:10001
CMD ["sleep", "infinity"]