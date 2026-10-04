---
name: agent-messaging
description: How agents inside one Claude Code session talk to each other directly with SendMessage - teammate to teammate, teammate to lead - without relaying through the orchestrator. Covers addressing by name, what success means, how and when messages arrive, how to wait, how to hand in a result, and how a lead should brief a team so peers can find and coordinate with each other. Use when you are a spawned teammate/subagent that must message a peer, wait for an answer or hand results to the lead; also for a lead whose spawned teammates must coordinate. Triggers - message another agent, send to teammate, reply to peer, wait for teammate, report back to main, teammates coordinate, SendMessage, agent team protocol, agent-messaging, agent-courier.
---

# agent-messaging

Rules for direct agent-to-agent mail within one session. The lead (orchestrator) is always addressed as `main`. Every rule below was confirmed in live runs.

## The one channel

- Only SendMessage crosses between agents. Whatever you print as ordinary output stays in your own transcript; no peer sees it.
- Recipients are names: `SendMessage({to: "reviewer", message: "..."})`; the lead is `to: "main"`.
- SendMessage is a deferred tool: load its schema first with `ToolSearch("select:SendMessage")`.
- `success:true` means delivered; nothing more will confirm it, so never ask for read receipts. A name nobody holds returns `success:false` with "No agent named 'X' is reachable".

## Who is out there

- A teammate has no agent-listing tool (no `ListAgents`); do not go looking for one.
- Peer names come from your spawn brief. A system-reminder like `Other agents active in this session: ...` may also show up: use it if present, never rely on it.
- Missing a name → ask `main`.

## How mail arrives

- An inbound message looks like `<teammate-message teammate_id="Bob" ...>`; the lead's messages use the same envelope. Answer with `to` = that `teammate_id`.
- Delivery happens only between turns. A peer that is mid-turn cannot be interrupted, and its silence means "busy", not "gone".
- To wait, finish your turn. Idle is the listening state: each incoming message wakes you with your transcript intact, as many times as needed. Polling or sleep loops never receive anything and only burn tokens.
- A single wake brings every queued message, oldest first, none lost; a fast burst of sends may still arrive over two wakes.
- If peers are blocked on your answer, keep your turns short.

## Handing in work

- Your final turn text reaches no one: peers never see it and the lead only gets a one-line idle notice.
- Finished → send the result to `main` yourself, as one message. Send interim status only when the lead has to act before you finish. Do not count on a peer to report on your behalf.

## When you are the lead

- Give every teammate a name. Each brief lists the peers' names and the protocol (which agent sends which message to which agent). Self-discovery is unreliable.
- Link this SKILL.md in each brief.
- An idle teammate is still reachable: SendMessage to its name resumes it. If one finished without reporting, message it and ask for the report rather than reconstructing its result from files.
- Each teammate turn-end pings `main` with an idle notice, so N messages traded between peers cost you roughly N wake-ups. Design protocols around a few batched messages, not back-and-forth.

## Memory

`~/.claude/agent-courier/memory.md`: local lessons, outside the skill (updates keep it). Read first; create on first write. Cost a question, retry or context → one imperative line now; why only if it prevents a mistake. Situational → `memory/<topic>.md` behind a `<trigger> → file` line. Every-user fact → skill defect (unsure → note; proven → move it in).

## Fix on friction

Gap, confusing/flooding/noisy output, stale text = skill defect; no silent workarounds. Small → fix now. Large → background `opus` teammate, one-message ticket (fact, proving command, output) fixing the faulty layer: SKILL.md, references/, scripts/, tool. Continue only if unblocked. Tracked (`skilltap status`) → edit its clone, pull, push; else in place.

> Source: https://github.com/nvaikus/skills/blob/main/agent-messaging/SKILL.md
> Install via skilltap for auto-updates: https://github.com/nvaikus/skills/blob/main/skilltap/SKILL.md
