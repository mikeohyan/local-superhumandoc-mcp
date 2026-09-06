"""The boundary that translates client failures into ToolError.

Only ClientError and its subclasses cross this boundary as a message the model
sees. Anything else is a bug in this server and is left to the SDK, which
redacts it — surfacing it verbatim would leak internals.
"""

import functools

from mcp.server.mcpserver.exceptions import ToolError

from superhumandoc_mcp.errors import ClientError


def tool_boundary(fn):
    """Translate the client's typed failures into ToolError, and nothing else.

    Only ClientError and its subclasses cross this boundary as a message the
    model sees. Anything else is a bug in this server and is left to the SDK,
    which redacts it — surfacing it verbatim would leak internals.
    """

    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        try:
            return await fn(*args, **kwargs)
        except ClientError as failure:
            raise ToolError(str(failure)) from failure

    return wrapper
