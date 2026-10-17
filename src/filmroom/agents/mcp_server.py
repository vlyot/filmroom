"""The engine tools as an MCP server, served by the API at /mcp over streamable HTTP. The analyst calls it
there, and any MCP client (Claude Code, an IDE) can too. The tools are read-only.

Store calls run in a worker thread: EngineStore analyses a match on its first request, which takes seconds
and would otherwise block the event loop the API and the analyst share.
"""

import functools
from collections.abc import Callable

import anyio
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations

from filmroom.agents.tools import EngineTools

INSTRUCTIONS = (
    "FilmRoom's engine: flagged football moments where a move broke down while a better option existed, "
    "judged under tactical style presets. Every number comes from a deterministic engine."
)
READ_ONLY = ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False)


def _in_thread(tool: Callable) -> Callable:
    @functools.wraps(tool)
    async def run(**arguments):
        return await anyio.to_thread.run_sync(functools.partial(tool, **arguments))

    return run


def build_mcp(tools: EngineTools) -> FastMCP:
    # The API is public and the tools read-only, so DNS-rebinding protection (on by default for a localhost
    # host) would only reject requests that reach the API under its public hostname.
    mcp = FastMCP(
        "filmroom-engine",
        instructions=INSTRUCTIONS,
        stateless_http=True,
        json_response=True,
        log_level="WARNING",
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )
    for tool in tools.all():
        mcp.add_tool(_in_thread(tool), name=tool.__name__, description=tool.__doc__, annotations=READ_ONLY)
    return mcp
