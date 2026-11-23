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

- **Hermes Agent** running inside a dedicated Docker container.
- **Docker Compose** for reproducible services, isolated networks, and disposable lab state.
- **A purpose-built MCP server** serving benign and adversarial test fixtures.
- **OpenTelemetry and Langfuse** for correlated traces of model calls, tool use, defense decisions, and observed outcomes.
- **Granite Switch** for evaluating decision-model-assisted defenses alongside deterministic controls.

```text
Hermes Agent <----------> MCP scenario server
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
export COMPOSE_FILE=compose.yaml:compose.langfuse.yaml  # optional: adds Langfuse tracing
docker compose up -d
docker compose logs -f hermes
```

Wait for `[hermes] provider: bob-proxy ..., mcp: lab, tracing: ...` before chatting. If you set `COMPOSE_FILE`, keep it set in that shell, or the next `docker compose up` recreates Hermes with tracing off.

### Talk to Hermes

```sh
docker compose exec hermes hermes                        # interactive chat
docker compose exec hermes hermes chat -Q -q "question"  # one-off answer, then exit
docker compose exec hermes hermes chat --continue        # resume the last session
docker compose exec hermes hermes -m explorer            # use a different Bob model
```

Hermes asks before running commands; add `--yolo` to skip the approvals.

Things to try:

- Ask it to use the lab tools, e.g. "save a note titled X with the lab tools, then list notes".
- Files it creates appear in `./data/workspace`.
- `docker compose exec hermes hermes mcp list` shows the connected MCP server.
- `docker compose exec hermes hermes sessions list` shows past chats.

### Try OpenCode (synthetic baseline)

OpenCode is a one-shot Compose service in the `demo` profile. Targeting `opencode` with `docker compose run` activates the profile for that run; plain `docker compose up -d` still starts the standard lab without OpenCode. The image includes [OpenCode](https://opencode.ai/docs/) `1.19.6` for Linux amd64 and arm64, so no host installation is needed. Compose expects `.env` to exist for both commands; only the demo needs valid Bob credentials.

```sh
# List configured models without starting the proxy or sending a model request:
docker compose run --rm --build --no-deps opencode --check
# After filling in .env, run the demo; Compose starts the proxy if needed:
docker compose run --rm --build opencode --model premium
```

The service connects to `bob-proxy` over the Compose network, starts in a temporary workspace with fresh OpenCode state, and emits JSON events to stdout. It sends a fixed synthetic summarization prompt, denies tool use, and does not register the lab MCP server or mount the lab workspace. This is a runtime baseline, not a scenario replay. A real run sends the synthetic prompt to the configured Bob backend.

### Traces

With Langfuse enabled, open http://localhost:3000 and log in with `LANGFUSE_ADMIN_EMAIL` / `LANGFUSE_ADMIN_PASSWORD` from `.env`. Each chat turn appears as a "Hermes turn" trace.

### Stop

`docker compose down` stops everything and keeps Hermes and Langfuse data; `docker compose down -v` also deletes it.

### Services

| Service | Role |
|---|---|
| `hermes` | Hermes Agent; works in `./data/workspace`, logs to `./data/logs` (gitignored) |
| `opencode` | One-shot synthetic OpenCode baseline (optional `demo` profile) |
| `bob-proxy` | OpenAI/Anthropic-compatible proxy to Bob's LLM backend (`llm/bob-provider`) |
| `mcp` | Example FastMCP scenario server (`mcp/`), registered in Hermes as `lab` |
| `langfuse-*` + datastores | Optional trace collection (`compose.langfuse.yaml`) |

## Roadmap

- [ ] Establish the lab threat model and reproducibility requirements.
- [x] Run a pinned Hermes configuration inside Docker.
- [x] Connect agent and tool events to Langfuse.
- [ ] Implement the MCP scenario server and benign task baseline.
- [ ] Add the first goal-hijack scenario and independent outcome checks.
- [ ] Implement the rules-only InstallGuard baseline.
- [ ] Integrate Granite Switch in observation-only mode, then evaluate enforcement.
- [ ] Add a memory/context-poisoning module.
- [ ] Publish reset procedures, experiment results, and a beginner-friendly lab guide.
- [ ] Assess whether training a specialist adapter is justified.

## References

- [OWASP Top 10 for Agentic Applications 2026](https://genai.owasp.org/resource/owasp-top-10-for-agentic-applications-for-2026)
- [Hermes Agent](https://github.com/NousResearch/hermes-agent)
- [Hermes documentation](https://hermes-agent.nousresearch.com/docs/)
- [Model Context Protocol](https://modelcontextprotocol.io/)
- [OpenTelemetry](https://opentelemetry.io/)
- [Langfuse](https://langfuse.com/)
- [Granite Switch](https://github.com/generative-computing/granite-switch)
- [Granite decision adapter](https://huggingface.co/ibm-granite/granitelib-core-r1.0/raw/main/decision/README.md)

## License

A project license has not yet been selected. A `LICENSE` file will be added once that decision is made.
