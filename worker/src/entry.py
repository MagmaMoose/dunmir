"""Cloudflare Python Worker entrypoint.

Bridges the Workers runtime to the FastAPI ASGI app and runs the cron sweep. The
``asgi`` helper is provided by the Workers Python runtime and passes ``self.env``
(D1, R2, vars, secrets) into the ASGI scope, where ``deps.get_env`` reads it.
"""

from workers import WorkerEntrypoint
import asgi

from app import app
from env import Env
from scheduled import run_scheduled_sweep


class Default(WorkerEntrypoint):
    async def fetch(self, request):
        return await asgi.fetch(app, request, self.env)

    async def scheduled(self, controller):
        # Run the dead-man-alert sweep; fan-out runs via waitUntil so the cron
        # invocation can return promptly.
        await run_scheduled_sweep(Env(self.env), self.ctx)
