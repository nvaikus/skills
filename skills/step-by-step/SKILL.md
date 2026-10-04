---
name: step-by-step
description: Puts Claude into a one-decision-at-a-time cadence for planning and design talks. Every meaningful choice is offered as a short standalone proposal, and Claude waits for the user's go-ahead before raising the next one, so an early wrong call is caught before later choices are built on it. Use whenever the user invokes it as a slash command, asks to slow down, says "go step by step" or "one thing at a time", wants to "discuss first, before doing everything", tells Claude to "stop planning ahead", or signals that a previous all-at-once answer was hard to review. Lasts through the planning part of the current task and switches itself off once the plan is agreed; it shapes the discussion only, never the execution of agreed work. Triggers - step by step, one at a time, slow down, don't plan everything at once, let's agree first, too much at once, по шагам, давай по одному.
---

# step-by-step

A cadence for planning and design talk, not for doing the work. Choices arrive singly, letting the user steer before a wrong early call drags dependent choices down with it.

## The loop

1. Put the next choice as a proposal: 1–3 sentences, plus a reason only when it is not obvious.
2. Close with a tiny check ("OK?", "Agreed?", "Go?") and nothing else.
3. Stop and wait.
4. A yes → next choice. A no, an objection or a question → talk it through briefly, settle it, then continue.
5. Everything settled → summarise what was agreed as 3–8 bullets and leave the mode.

Write each proposal so a single word ("yes", "ok", "+") is a full answer. The user's effort per turn is the cost to minimise.

## What gets raised

Raise a choice when option A vs option B changes the work that follows:

- approach or strategy (background worker vs inline await)
- where a boundary goes (extend the current module or add one)
- library or dependency
- data shape, schema, the name of anything others will see
- scope cuts ("X now, explicitly not Y")
- ordering, when one step blocks another

Settle silently, without asking: local names, formatting, obvious refactors, follow-ups an agreed choice already forces, anything the user handed over to you.

## Size of a step

- One choice per proposal, even when you already see the next two.
- Allowed pair: B only makes sense given A and they stand or fall together. Raise them together, just as short, and say how they depend.
- Never several independent choices in one message.
- "What's still ahead?" → list the upcoming choices as a map, not for answering in bulk, then go back to one at a time.
- Over ~4 lines → split it or cut the reasoning.

Keep out of this mode: a full plan in bullets, trade-off tables over every alternative, echoing back what the user just said, and hedged menus ("A, B or C, your call?"). Pick one and propose it; the user will push back if needed.

Good shapes: "I'd go with X, because Y. OK?" · "I'll put it in `foo/bar.py`. Fine?" · "Validate first, then write. Go?"

## Not sure what to propose

Ask the one question that decides it, not a questionnaire, then propose.

- Bad: "Which database, how much traffic, do we need retries, who owns alerting?"
- Good: "Do writes come from one service or several? That decides whether we need locking."

## Leaving the mode

Leave on your own once the final open choice has the user's yes, you foresee no further design question that would block the work, and the plan can be stated cleanly. Give the 3–8 bullet recap, say plainly that step-by-step is over and you are starting, then work normally: edits, tool calls and multi-step actions need no per-step confirmation.

The user says stop / exit / "carry on yourself" earlier → leave at once with whatever recap exists.

## While carrying out the plan

The mode governs talk, not execution. Do not ask permission for each edit and do not re-confirm settled choices. Exception: a new choice with real downstream impact that the plan did not cover → raise just that one in the same proposal-and-check form, get the answer, carry on.

## Tone

Reply in the user's language, proposals and checks included. Direct and friendly: a collaboration rhythm, not an interrogation.

## Memory

`~/.claude/step-by-step/memory.md`: local lessons, outside the skill (updates keep it). Read first; create on first write. Cost a question, retry or context → one imperative line now; why only if it prevents a mistake. Situational → `memory/<topic>.md` behind a `<trigger> → file` line. Every-user fact → skill defect (unsure → note; proven → move it in).

## Fix on friction

Gap, confusing/flooding/noisy output, stale text = skill defect; no silent workarounds. Small → fix now. Large → background `opus` teammate, one-message ticket (fact, proving command, output) fixing the faulty layer: SKILL.md, references/, scripts/, tool. Continue only if unblocked. Tracked (`skilltap status`) → edit its clone, pull, push; else in place.

> Source: https://github.com/nvaikus/skills/blob/main/skills/step-by-step/SKILL.md
> Install via skilltap for auto-updates: https://github.com/nvaikus/skills/blob/main/skills/skilltap/SKILL.md
