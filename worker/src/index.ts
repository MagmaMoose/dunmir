import { Hono } from "hono";
import type { AppContext, Env } from "./env";
import admin from "./routes/admin";
import dashboard from "./routes/dashboard";
import ingest from "./routes/ingest";
import read from "./routes/read";
import { runScheduledSweep } from "./scheduled";

const app = new Hono<AppContext>();

app.onError((err, c) => {
  console.error("unhandled", err);
  return c.json({ error: "internal_error" }, 500);
});

app.notFound((c) => c.json({ error: "not_found" }, 404));

app.route("/v1/ingest", ingest);
app.route("/v1/admin", admin);
app.route("/v1", read);
app.route("/", dashboard);

export default {
  fetch: app.fetch,
  async scheduled(_controller, env, ctx) {
    ctx.waitUntil(runScheduledSweep(env, ctx));
  },
} satisfies ExportedHandler<Env>;
