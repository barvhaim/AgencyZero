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

Inspector logging is independent of Langfuse and can be enabled without running the Langfuse services.

With Inspector enabled, events are written to `./data/inspector-logs/inspector.jsonl`. The JSONL file contains recorded tool calls, LLM turns, and provider request metadata. Depending on the captured event, records may include conversation content, tool inputs, and tool outputs. Each line represents a separate JSON event.

**Use synthetic data only when running experiments.** Inspector logs may contain sensitive information from conversations and tool interactions. Treat the log file as potentially sensitive and avoid using real credentials, personal information, or confidential data.

To inspect the log:

```sh
# Follow new events
tail -f data/inspector-logs/inspector.jsonl

# View the complete log
cat data/inspector-logs/inspector.jsonl
```

Inspector logging is optional and can be enabled through `compose.inspector.yaml`.

> [!WARNING]
> **Inspector logs are not tamper-proof against the agent.**
> The Inspector plugin runs inside the Hermes container, in the agent's own process. Everything it reports is the agent's own account of what happened, not independent evidence.
>
> - The agent can read `INSPECTOR_KEY`, so a compromised or hijacked agent can post forged events that look identical to real ones.
> - A compromised agent can also alter what the hooks report, disable the plugin, or stop sending events altogether. A missing event does not prove the action didn't happen.
> - The shared secret only keeps *other* containers on the `lab` network from writing to the log. It does not protect the log from the agent under test or anything with access to the container environment containing the key.
> - The log is append-only by convention, not tamper-evident. Anyone with write access to `./data/inspector-logs` can edit it.
> - The log has a size cap (`INSPECTOR_MAX_LOG_BYTES`, default 100 MB). Once it's reached, new events are rejected and recording stops.
>
> Use Inspector as a convenient debugging and observation aid. Don't use it as the sole basis for conclusions about attack success or defense effectiveness in adversarial experiments. For those, rely on observations made from outside the agent container, such as workspace diffs, MCP server records, and proxy-side logs, and treat Inspector data as a claim to cross-check against them.
> you can find such fabrication proof in logger/risk_proof.jsonl, where it stole the key and created a fake trace with Event type: "test_event".
> trying to do the same for langfuse failed, for some reason everytime hermes tries to read the langfuse keys they come back empty despite they being there when retrieved manually via printenv. would like to know how they achieved that but thats a concern for later.

a small explanation for risk_proof, i've asked hermes to read the env key, check the plugin details and send a fabricated event. the event is found near the end, the key was fabricated anyway but still make sure you dont reuse it.
a similar test with langfuse produced an interesting result, while manual printenv did provide me the keys, hermes was always getting empty results despite seing the vars themself, this is still not a proof that langfuse is immune though.

**Optional stream capture**

Inspector can also record incremental model output through Hermes streaming hooks. By default, both stream capture options are disabled.

To change them, edit `plugins/inspector/__init__.py`:

```python
CAPTURE_TEXT_DELTA_STREAM = False
CAPTURE_REASONING = False
```

- `CAPTURE_TEXT_DELTA_STREAM`: Records incremental text output. Usually unnecessary because completed assistant responses are already captured by `post_llm_call`.
- `CAPTURE_REASONING`: Records reasoning deltas exposed by the provider. This can substantially increase log size.

Set either option to `True` to enable its capture. Restart Hermes after changing the plugin so the changes take effect.

These options affect Inspector logging, not the model's reasoning capabilities.

### Stop

`docker compose down` stops everything and keeps Hermes and Langfuse data; `docker compose down -v` also deletes it, but does not delete host directories such as `./data/inspector-logs`..

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
