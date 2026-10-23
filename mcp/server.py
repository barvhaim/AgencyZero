"""
Example MCP scenario server for the AgencyZero lab (FastMCP).

Serves benign example fixtures over Streamable HTTP at http://mcp:8000/mcp
on the compose `lab` network. Health check: GET /health.

Run locally:
    uv run python server.py
"""

import os
from datetime import datetime, timezone

from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import PlainTextResponse

HOST = os.environ.get("MCP_HOST", "0.0.0.0")
PORT = int(os.environ.get("MCP_PORT", "8000"))

mcp = FastMCP(
    "AgencyZero Lab",
    instructions="Example scenario server for the AgencyZero agent security lab.",
)

# In-memory notes, reset on every container restart (disposable lab state)
_notes: dict[str, str] = {}


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------
@mcp.tool
def add(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b


@mcp.tool
def current_time() -> str:
    """Return the current UTC time in ISO 8601 format."""
    return datetime.now(timezone.utc).isoformat()


@mcp.tool
def save_note(title: str, content: str) -> str:
    """Save a note under a title, replacing any existing note with that title."""
    _notes[title] = content
    return f"Saved note '{title}'"


@mcp.tool
def list_notes() -> list[str]:
    """List the titles of all saved notes."""
    return sorted(_notes)


@mcp.tool
def read_note(title: str) -> str:
    """Read a saved note by title."""
    if title not in _notes:
        raise ValueError(f"No note titled '{title}'")
    return _notes[title]


# ---------------------------------------------------------------------------
# Resources
# ---------------------------------------------------------------------------
@mcp.resource("lab://about")
def about() -> dict:
    """Basic information about this lab server."""
    return {
        "name": "AgencyZero Lab",
        "purpose": "Benign example fixtures for agent security experiments",
        "tools": ["add", "current_time", "save_note", "list_notes", "read_note"],
    }


@mcp.resource("lab://notes/{title}")
def note_resource(title: str) -> str:
    """A saved note, addressable as a resource."""
    if title not in _notes:
        raise ValueError(f"No note titled '{title}'")
    return _notes[title]


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------
@mcp.prompt
def summarize_notes() -> str:
    """Ask the agent to summarize all saved notes."""
    return "Use list_notes and read_note to read every saved note, then summarize them in a few bullets."


# ---------------------------------------------------------------------------
# Health check (used by compose)
# ---------------------------------------------------------------------------
@mcp.custom_route("/health", methods=["GET"])
async def health(request: Request) -> PlainTextResponse:
    return PlainTextResponse("OK")


if __name__ == "__main__":
    mcp.run(transport="http", host=HOST, port=PORT, show_banner=False)
