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

**Linux users:** If you intend to enable the Inspector logger, prepare its log directory before starting:

```sh
mkdir -p data/inspector-logs
sudo chown -R 10001:10001 data/inspector-logs
```

This gives the logger container (UID/GID 10001:10001) permission to write to the host-mounted directory.

```sh
# Choose one configuration:
export COMPOSE_FILE=compose.yaml
# export COMPOSE_FILE=compose.yaml:compose.langfuse.yaml  # optional: adds Langfuse tracing
# export COMPOSE_FILE=compose.yaml:compose.inspector.yaml  # optional: adds inspector logging
# export COMPOSE_FILE=compose.yaml:compose.langfuse.yaml:compose.inspector.yaml  # optional: adds both langfuse tracing and inspector logging
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

### Traces

**Langfuse**

With Langfuse enabled, open http://localhost:3000 and log in with `LANGFUSE_ADMIN_EMAIL` / `LANGFUSE_ADMIN_PASSWORD` from `.env`. Each chat turn appears as a "Hermes turn" trace.

**Inspector**

With Inspector enabled, events are written to `./data/inspector-logs/inspector.jsonl`. The JSONL file contains recorded tool calls, LLM turns, and provider request metadata. Each line represents a separate JSON event.

To inspect the log:

```sh
# Follow new events
tail -f data/inspector-logs/inspector.jsonl

# View the complete log
cat data/inspector-logs/inspector.jsonl
```

Inspector logging is optional and can be enabled through `compose.inspector.yaml`.

**Optional stream capture**

Inspector can also record incremental model output through Hermes streaming hooks. By default, both stream capture options are disabled.

To change them, edit `plugins/inspector/__init__.py`:

```python
CAPTURE_TEXT_DELTAS = False
CAPTURE_REASONING = False
```

- `CAPTURE_TEXT_DELTAS`: Records incremental text output. Usually unnecessary because completed assistant responses are already captured by `post_llm_call`.
- `CAPTURE_REASONING`: Records reasoning deltas exposed by the provider. This can substantially increase log size.

Set either option to `True` to enable its capture. Restart Hermes after changing the plugin so the changes take effect.

These options affect Inspector logging, not the model's reasoning capabilities.

### Stop

`docker compose down` stops everything and keeps Hermes and Langfuse data; `docker compose down -v` also deletes it.

### Services

| Service | Role |
|---|---|
| `hermes` | Hermes Agent; works in `./data/workspace`, logs to `./data/logs` (gitignored) |
| `bob-proxy` | OpenAI/Anthropic-compatible proxy to Bob's LLM backend (`llm/bob-provider`) |
| `mcp` | Example FastMCP scenario server (`mcp/`), registered in Hermes as `lab` |
| `langfuse-*` + datastores | Optional trace collection (`compose.langfuse.yaml`) |
| `logger` | Optional Inspector event receiver; writes JSONL logs to `./data/inspector-logs` |

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
