// Dev-only in-memory /api for `npm run mock` (vite --mode mock). Never shipped:
// vite.config.ts loads it only in mock mode. Shapes follow the HTTP API contract
// in clockmaster-cli/src/CLAUDE.md. Plain JS on purpose (tsc covers src/ only).

const H = 3600e3;
const M = 60e3;

const iso = (t) => new Date(t).toISOString();

function makeTasks() {
  const base = {
    description: "",
    enabled: true,
    notify: "failure",
    sound: "Blow",
    workdir: "~",
    timeoutSec: 7200,
    keep: 50,
    state: "ok",
    drift: false,
    group: "",
  };
  return [
    { ...base, name: "morning-digest", group: "reports", schedule: "0 9 * * 1-5", scheduleText: "every weekday at 9:00", command: 'claude -p "summarize my inbox" --session-id "$TASK_SESSION_ID"', description: "Inbox summary before work", everyMin: 24 * 60, at: 9 * 60, dur: 95, claude: true, notify: "on" },
    { ...base, name: "weekly-report", group: "reports", schedule: "30 17 * * 5", scheduleText: "every Friday at 17:30", command: "python3 report.py --week", everyMin: 7 * 24 * 60, at: 17 * 60 + 30, dur: 40 },
    { ...base, name: "db-backup", group: "backups", schedule: "15 2 * * *", scheduleText: "every day at 2:15", command: "pg_dump app > /backups/app.sql", everyMin: 24 * 60, at: 2 * 60 + 15, dur: 300, description: "Nightly database dump" },
    { ...base, name: "photos-sync", group: "backups", schedule: "0 */4 * * *", scheduleText: "every 4 hours", command: "rclone sync ~/Photos remote:photos", everyMin: 240, at: 0, dur: 900, live: true, sound: "Glass" },
    { ...base, name: "hello", schedule: "*/30 * * * *", scheduleText: "every 30 minutes", command: "echo hi", everyMin: 30, at: 0, dur: 1, notify: "off", sound: "off" },
    { ...base, name: "flaky-check", schedule: "0 * * * *", scheduleText: "every hour", command: "curl -fsS https://example.invalid/health", everyMin: 60, at: 0, dur: 3, flaky: true, state: "stale", drift: true, description: "Health probe that fails now and then" },
    { ...base, name: "old-cleanup", enabled: false, state: "off", schedule: "0 3 1 * *", scheduleText: "on day 1 of every month at 3:00", command: "find /tmp -mtime +30 -delete", everyMin: 30 * 24 * 60, at: 3 * 60, dur: 12 },
  ];
}

function plannedTimes(t, from, to) {
  const out = [];
  const d0 = new Date(from);
  d0.setHours(0, 0, 0, 0);
  const step = t.everyMin * M;
  for (let x = d0.getTime() + t.at * M; x <= to; x += step) if (x >= from) out.push(x);
  return out;
}

function makeRuns(t, now) {
  const runs = [];
  let i = 0;
  for (const s of plannedTimes(t, now - 8 * 24 * H, now).reverse()) {
    if (runs.length >= 60) break;
    i++;
    let status = "success";
    if (t.flaky && i % 4 === 2) status = "failed";
    if (t.flaky && i === 7) status = "timeout";
    if (t.name === "db-backup" && i === 3) status = "killed";
    const dur = t.dur * (0.7 + ((i * 37) % 10) / 15);
    const run = {
      task: t.name,
      runId: runIdOf(s, 4000 + i),
      trigger: "schedule",
      command: t.command,
      workdir: t.workdir,
      start: iso(s),
      end: iso(s + dur * 1000),
      status,
      exitCode: status === "success" ? 0 : status === "failed" ? 7 : null,
      durationSec: Math.round(dur * 10) / 10,
      hasSession: !!t.claude,
      sessionId: t.claude ? "5b1c2d3e-0000-4000-8000-" + String(i).padStart(12, "0") : undefined,
      costUsd: t.claude ? Math.round((0.04 + (i % 5) * 0.031) * 1000) / 1000 : null,
    };
    if (t.enabled || i > 3) runs.push(run);
  }
  if (t.live) {
    runs.unshift({ task: t.name, runId: runIdOf(now - 4 * M, 999), trigger: "schedule", command: t.command, workdir: t.workdir, start: iso(now - 4 * M), status: "running", exitCode: null, durationSec: null, hasSession: false, costUsd: null });
  }
  return runs;
}

function runIdOf(t, pid) {
  const d = new Date(t);
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}-${p(d.getHours())}${p(d.getMinutes())}${p(d.getSeconds())}-${pid}`;
}

function logFor(run, now) {
  const lines = [`$ ${run.command}`];
  const n = run.status === "running" ? Math.floor((now - Date.parse(run.start)) / 2000) : 18;
  for (let k = 0; k < Math.min(n, 400); k++) lines.push(`[${String(k).padStart(3, "0")}] processing chunk ${k} … ok`);
  if (run.status === "failed") lines.push("curl: (6) Could not resolve host: example.invalid", "exit 7");
  if (run.status === "success") lines.push("done.");
  if (run.costUsd) lines.push(`TASK_COST_USD=${run.costUsd}`);
  return lines.join("\n") + "\n";
}

export function mockApi() {
  const now0 = Date.now();
  const tasks = makeTasks();
  const runs = new Map(tasks.map((t) => [t.name, makeRuns(t, now0)]));
  let pendingClick = null;

  const finish = (r, status, now) => {
    r.status = status;
    r.end = iso(now);
    r.durationSec = Math.round((now - Date.parse(r.start)) / 100) / 10;
    r.exitCode = status === "success" ? 0 : null;
  };
  const tick = (now) => {
    for (const list of runs.values())
      for (const r of list)
        if (r.status === "running" && r.manual && now - Date.parse(r.start) > 20e3) finish(r, "success", now);
  };
  const avgOf = (name) => {
    const ds = (runs.get(name) ?? []).slice(0, 20).filter((r) => (r.status === "success" || r.status === "failed") && r.durationSec != null).map((r) => r.durationSec);
    return ds.length ? Math.round((ds.reduce((a, b) => a + b, 0) / ds.length) * 10) / 10 : null;
  };
  const nextRunOf = (t, now) => (t.enabled ? iso(plannedTimes(t, now, now + 40 * 24 * H)[0] ?? null) : null);
  const taskJson = (t, now) => {
    const list = runs.get(t.name) ?? [];
    // eslint-disable-next-line no-unused-vars
    const { everyMin, at, dur, claude, flaky, live, ...pub } = t;
    return { ...pub, nextRun: nextRunOf(t, now), lastRun: list[0] ?? null, avgDurationSec: avgOf(t.name), lastRuns: list.slice(0, 20).map((r) => ({ runId: r.runId, status: r.status, start: r.start, durationSec: r.durationSec, trigger: r.trigger })) };
  };

  return {
    name: "clockmaster-mock-api",
    configureServer(server) {
      server.middlewares.use(async (req, res, next) => {
        const url = new URL(req.url, "http://x");
        if (!url.pathname.startsWith("/api/")) return next();
        const now = Date.now();
        tick(now);
        let body = {};
        if (req.method === "POST") {
          let raw = "";
          for await (const c of req) raw += c;
          try { body = raw ? JSON.parse(raw) : {}; } catch { body = {}; }
        }
        const send = (code, obj, type = "application/json") => {
          res.statusCode = code;
          res.setHeader("Content-Type", type);
          res.end(type === "application/json" ? JSON.stringify(obj) : obj);
        };
        const p = url.pathname.split("/").slice(2).map(decodeURIComponent);
        await new Promise((r) => setTimeout(r, 60));
        const task = p[0] === "tasks" && p[1] ? tasks.find((t) => t.name === p[1]) : null;
        if (p[0] === "tasks" && p[1] && !task) return send(404, { error: `no task '${p[1]}'` });

        if (p[0] === "app") return send(200, { app: "clockmaster", platform: "linux", backend: "systemd", dataDir: "~/.claude/clockmaster", notes: ["Lingering is off for this user: tasks run only while you are logged in. Enable with: loginctl enable-linger"], sounds: ["Basso", "Blow", "Bottle", "Frog", "Funk", "Glass", "Hero", "Morse", "Ping", "Pop", "Purr", "Sosumi", "Submarine", "Tink"], canOpenTerminal: false, notifyChannels: ["Telegram"] });
        if (p[0] === "drift") return send(200, { drift: tasks.filter((t) => t.drift).length });
        // no cron parser in the mock: echo the cron as its own words (the real server describes it)
        if (p[0] === "schedule") { const c = (url.searchParams.get("cron") || "").trim(); return c.split(/\s+/).length === 5 ? send(200, { cron: c, text: c, next: [] }) : send(400, { error: "schedule needs 5 cron fields" }); }
        if (p[0] === "notify-click") { const c = pendingClick; pendingClick = null; return send(200, c ?? {}); }
        if (p[0] === "sync" && req.method === "POST") { for (const t of tasks) { t.drift = false; t.state = t.enabled ? "ok" : "off"; } return send(200, { ok: true, output: "~ flaky-check: scheduled '0 * * * *' (1 intervals)\nsync done: 1 scheduled, 1 changed, 5 unchanged" }); }
        if (p[0] === "timeline") {
          const from = Date.parse(url.searchParams.get("from")), to = Date.parse(url.searchParams.get("to"));
          return send(200, tasks.map((t) => ({
            task: t.name, group: t.group, enabled: t.enabled,
            runs: (runs.get(t.name) ?? []).filter((r) => Date.parse(r.start) < to && (r.end ? Date.parse(r.end) : now) > from).map(({ runId, start, end, durationSec, status, trigger, exitCode }) => ({ runId, start, end: end ?? null, durationSec, status, trigger, exitCode })),
            planned: t.enabled ? plannedTimes(t, Math.max(from, now), to).slice(0, 1000).map(iso) : [],
            plannedTruncated: false,
            plannedEvery: 1,
            avgDurationSec: avgOf(t.name),
          })));
        }
        if (p[0] === "tasks" && !p[1]) return send(200, tasks.map((t) => taskJson(t, now)));
        if (task && p.length === 2 && req.method === "GET") {
          const spent = (runs.get(task.name) ?? []).reduce((a, r) => a + (r.costUsd ?? 0), 0);
          return send(200, { ...taskJson(task, now), yaml: `schedule: "${task.schedule}"\ncommand: ${task.command}\n`, spentUsd: task.claude ? spent : null });
        }
        if (task && p.length === 2 && req.method === "POST") {
          if (body.schedule === "bad") return send(400, { error: "schedule: expected 5 fields, got 1" });
          if (body.name && body.name !== task.name) {
            if (tasks.some((t) => t.name === body.name)) return send(409, { error: `task '${body.name}' already exists` });
            const list = runs.get(task.name); runs.delete(task.name); task.name = body.name; runs.set(task.name, list);
            for (const r of list) r.task = task.name;
          }
          for (const k of ["schedule", "command", "workdir", "description", "group"]) if (k in body) task[k] = body[k];
          if ("timeout" in body) task.timeoutSec = body.timeout === "" ? 7200 : body.timeout === "none" ? null : parseInt(body.timeout) * 60;
          if ("keep" in body) task.keep = body.keep === "" ? 50 : body.keep === "unlimited" ? null : Number(body.keep);
          return send(200, { ok: true, name: task.name, syncOutput: `~ ${task.name}: scheduled` });
        }
        if (task && p.length === 2 && req.method === "DELETE") {
          tasks.splice(tasks.indexOf(task), 1);
          const purged = url.searchParams.get("purge-runs") === "1";
          if (purged) runs.delete(task.name);
          return send(200, { ok: true, deleted: task.name, purgedRuns: purged, syncOutput: `- ${task.name}: removed` });
        }
        if (task && p[2] === "run") {
          const r = { task: task.name, runId: runIdOf(now, 5000 + Math.floor(Math.random() * 999)), trigger: "manual", command: task.command, workdir: task.workdir, start: iso(now), status: "running", exitCode: null, durationSec: null, hasSession: !!task.claude, costUsd: null, manual: true };
          setTimeout(() => runs.get(task.name).unshift(r), 500);
          setTimeout(() => { pendingClick = { task: task.name, runId: r.runId }; }, 60e3);
          return send(202, { started: true });
        }
        if (task && p[2] === "enabled") { task.enabled = !!body.enabled; task.state = task.enabled ? "ok" : "off"; return send(200, { ok: true, enabled: task.enabled, syncOutput: "" }); }
        if (task && p[2] === "notify") { task.notify = body.notify; return send(200, { ok: true, notify: task.notify }); }
        if (task && p[2] === "sound") { task.sound = body.sound; return send(200, { ok: true, sound: task.sound }); }
        if (task && p[2] === "runs" && !p[3]) return send(200, (runs.get(task.name) ?? []).slice(0, Number(url.searchParams.get("n") || 50)));
        const run = task && p[2] === "runs" ? (runs.get(task.name) ?? []).find((r) => r.runId === p[3]) : null;
        if (task && p[2] === "runs" && !run) return send(404, { error: "no such run" });
        if (run && p[4] === "log") return send(200, logFor(run, now), "text/plain; charset=utf-8");
        if (run && p[4] === "stop") { if (run.status === "running") finish(run, "stopped", now); return send(200, { run, note: "stopped" }); }
        if (run && p[4] === "resume") return send(200, { opened: false, command: `cd ~ && claude --resume ${run.sessionId}`, note: "No terminal can be opened here — copy the command." });
        return send(404, { error: "not found" });
      });
    },
  };
}
