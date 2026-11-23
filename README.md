# AgencyZero

**Break agents. Trace failures. Test defenses.**

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/az-logo-dark.png">
  <source media="(prefers-color-scheme: light)" srcset="assets/az-logo-light.png">
  <img alt="AgencyZero" src="assets/az-logo-dark.png" width="500">
</picture>

An open-source AI agent security research lab for reproducible attacks, observable failures, and defense evaluation.

## Why AgencyZero?

AI agent security is more than prompt injection. Agents use tools, act with delegated permissions, consume untrusted content, retain memory, and interact with other systems. Security failures can emerge anywhere along that path.

AgencyZero aims to provide a controlled environment for investigating those failures: define a legitimate task, introduce an adversarial condition, observe what the agent actually does, and measure whether a defense helps without preventing useful work.

The lab is intended for students, security researchers, and developers building agentic applications.

## Planned architecture

The first lab will be built around:

- **OpenCode** running inside a dedicated Docker container.
- **Docker Compose** for reproducible services, isolated networks, and disposable lab state.
- **A purpose-built MCP server** serving benign and adversarial test fixtures.
- **OpenTelemetry and Langfuse** for correlated traces of model calls, tool use, defense decisions, and observed outcomes.
- **Granite Switch** for evaluating decision-model-assisted defenses alongside deterministic controls.

```text
OpenCode <--------------> MCP scenario server (planned connection)
       |
       v
Defense integration ---> Granite Switch
       |
       v
Controlled action ---> Lab workspace / outcome checks

Agent, tool, and defense events
       |
       v
Telemetry integration ---> Langfuse
```

## Planned modules

### InstallGuard

Evaluate package installations proposed by the agent using the task context, the documented source of the recommendation, and evidence about the exact dependencies being installed.

The initial scope will use a closed catalog of lab packages and a controlled installation path—not unrestricted installation from public registries. The defense will combine deterministic policy with Granite Switch decisions and compare that combination against a rules-only baseline.

## Running the lab

Run all commands from the project root.

### Start

Copy `.env.sample` to `.env` and fill in the values, then:

```sh
docker compose up -d --build --wait
```

OpenCode is the default agent service. Starting the stack does not send a model request. The image includes [OpenCode](https://opencode.ai/docs/) `1.19.6` for Linux amd64 and arm64; no host installation is needed.

If you are upgrading a running stack that used Hermes, add `--remove-orphans` to the start command to remove the old service container. This does not delete its named volume.

### Run the OpenCode demo

```sh
# List configured models without sending a model request:
docker compose exec -T opencode python3 /app/baseline.py --check
# Run the synthetic demo with valid Bob credentials:
docker compose exec -T opencode python3 /app/baseline.py --model premium
```

The service connects to `bob-proxy` over the Compose network, starts in a temporary workspace with fresh OpenCode state, and emits JSON events to stdout. It sends a fixed synthetic summarization prompt, denies tool use, and does not register the lab MCP server or mount the lab workspace. This is a runtime baseline, not a scenario replay. A real run sends the synthetic prompt to the configured Bob backend.

### Traces

The OpenCode demo emits JSON events to stdout; it does not send traces to Langfuse. To run the optional Langfuse stack, fill in its settings in `.env`, then run `export COMPOSE_FILE=compose.yaml:compose.langfuse.yaml` before starting and stopping the lab. Open http://localhost:3000 and sign in with `LANGFUSE_ADMIN_EMAIL` / `LANGFUSE_ADMIN_PASSWORD`.

### Stop

`docker compose down` stops the stack and retains named volumes. `docker compose down -v` also deletes named volumes declared by the active Compose files.

### Services

| Service | Role |
|---|---|
| `opencode` | Default agent service; runs the synthetic baseline on demand |
| `bob-proxy` | OpenAI/Anthropic-compatible proxy to Bob's LLM backend (`llm/bob-provider`) |
| `mcp` | Example FastMCP scenario server (`mcp/`); not used by the OpenCode baseline |
| `langfuse-*` + datastores | Optional telemetry infrastructure (`compose.langfuse.yaml`) |

## Roadmap

- [ ] Establish the lab threat model and reproducibility requirements.
- [x] Package a pinned OpenCode configuration in Docker.
- [ ] Connect OpenCode agent and tool events to Langfuse.
- [ ] Connect OpenCode to the MCP scenario server for a benign tool demo.
- [ ] Add the first goal-hijack scenario and independent outcome checks.
- [ ] Implement the rules-only InstallGuard baseline.
- [ ] Integrate Granite Switch in observation-only mode, then evaluate enforcement.
- [ ] Add a memory/context-poisoning module.
- [ ] Publish reset procedures, experiment results, and a beginner-friendly lab guide.
- [ ] Assess whether training a specialist adapter is justified.

## References

- [OWASP Top 10 for Agentic Applications 2026](https://genai.owasp.org/resource/owasp-top-10-for-agentic-applications-for-2026)
- [OpenCode documentation](https://opencode.ai/docs/)
- [Model Context Protocol](https://modelcontextprotocol.io/)
- [OpenTelemetry](https://opentelemetry.io/)
- [Langfuse](https://langfuse.com/)
- [Granite Switch](https://github.com/generative-computing/granite-switch)
- [Granite decision adapter](https://huggingface.co/ibm-granite/granitelib-core-r1.0/raw/main/decision/README.md)

## License

A project license has not yet been selected. A `LICENSE` file will be added once that decision is made.
