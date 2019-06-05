"""Package defining various Utility features."""

from asyncio import gather

from .callbacks import callback_response
from .output import echo, err, P, set_colors, set_verbosity, warn


async def cleanup(tasks):
    print("Cleaning up...")
    for t in [t for t in tasks if not (t.done() or t.cancelled())]:
        t.cancel()
    g = gather(*tasks, return_exceptions=True)
    await g
