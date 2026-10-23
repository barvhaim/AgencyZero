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

Copy `.env.sample` to `.env` and fill in the values, then:

```sh
docker compose up -d
docker compose -f compose.yaml -f compose.langfuse.yaml up -d  # with Langfuse at http://localhost:3000
docker compose exec hermes hermes
```

| Service | Role |
|---|---|
| `hermes` | Hermes Agent; works in `./data/workspace`, logs to `./data/logs` (gitignored) |
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
