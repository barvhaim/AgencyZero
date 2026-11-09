set "COMPOSE_FILE=compose.yaml;compose.langfuse.yaml"
docker compose up -d --build mcp
docker compose logs -f hermes