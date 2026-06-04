"""One-shot dead-man-alert sweep for the portable deployment.

The Cloudflare Worker runs this on a cron trigger (``entry.scheduled``). Off
Cloudflare there's no built-in cron, so this module runs a single sweep against
Postgres and exits — drive it from a k8s ``CronJob`` (every minute) or any
scheduler.

    DATABASE_URL=postgres://… python -m sweep
"""

from __future__ import annotations

import asyncio

from env import StandaloneEnv
from scheduled import run_scheduled_sweep


async def _main() -> None:
    env = await StandaloneEnv.create()
    try:
        await run_scheduled_sweep(env)
    finally:
        await env.close()


def main() -> None:
    asyncio.run(_main())


if __name__ == "__main__":
    main()
