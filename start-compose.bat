set "COMPOSE_FILE=compose.yaml;compose.langfuse.yaml"
docker compose up -d
docker compose logs -f hermes