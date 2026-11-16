# Scenarios

One folder per scenario. The MCP server pre-loads `notes/*.md` as planted notes
when `AZ_SCENARIO` is set to the folder name (each file = one note; filename
without `.md` = title). `workspace/*` files are planted into `data/workspace`
by the runner. `scenario.json` holds the user message and the scoring rules.

Run one with:  .\lab.cmd run <scenario>
