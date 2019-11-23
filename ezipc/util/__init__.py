"""Package defining various Utility features."""

from asyncio import gather

from .callbacks import callback_response
from .output import echo, err, hl_method, hl_remote, newLogger, P, set_verbosity, T, warn


async def cleanup(tasks):
    print("Cleaning up...")
    for t in [t for t in tasks if not (t.done() or t.cancelled())]:
        t.cancel()
    g = gather(*tasks, return_exceptions=True)
    await g
