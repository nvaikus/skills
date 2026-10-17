# Groups: group mode, owner groups, peer bots, who a message is for

Setup steps for each mode: `setup.md`.

## Group mode (several people, one bot)

- When: a project bot that 2+ people drive, every topic visible to all. Config `group_id` (forum supergroup, `-100…`) + `allowed_users` (user ids); absent = private-owner mode (SKILL.md Security). Setup: `setup.md` (Group mode).
- Only `allowed_users` in that group are heard (empty list = nobody); everyone/everything else (other members, bots except Peer bots below, channel posts, anonymous admins) is ignored silently (one `ignored: …` log line per source per hour); `/cmd@other_bot` too. All allowed users are equal (commands, ⏹, everything); `owner_id` is unused. The bot leaves any other group it is added to.
- Topics, notify, spawn/send, restart reports all go to the group. Each prompt line is tagged `[From: Name (@user, id N)]`. Links: `https://t.me/c/<group id without -100>/<thread>/2147483647` (members only).
- General topic of any group (this and owner groups) is ignored by default: messages and commands (`/start` too), no reply, one log line per chat per hour. Work happens in topics. Config `group_general: true` = heard again (every message there opens a topic). Outbound (`notify` without a topic) still posts there. The private chat is unaffected. Join/pin/title service messages never run.
- Exception: a mention of the bot in General by an admitted sender (`@botname` in text/caption, a text mention of the bot, or a reply to one of the bot's messages) opens a new topic (title from the message, auto-renamed later) and replies in General with its link. The topic's first prompt = the last `general_context` (20) General messages, oldest first, in a delimited block + the mention. The bot sees General only as admin; the buffer holds only senders it admits (`allowed_users` / the owner), text + sender + time, media as `[photo]`-style placeholders, in `~/.local/share/claude-tg/general.json` (survives restarts).
- Telegram allows ~20 messages/min per group, edits included. Cosmetic budget (status edits, typing, stream edits) 0.2/s, burst 3 (private: 0.5/s, burst 5); answers are never dropped. `sendMessageDraft` is private-only → answers stream as an edited message.

## Owner groups (private mode + extra forum groups)

- When: one owner, topics of a project kept in their own forum group. Config `owner_groups`: `{"name": -100…}` (private mode only; ignored with `group_id`). Setup: `setup.md` (Owner groups).
- Connect / drop one only via `claude-tg group add NAME [ID]` / `remove NAME`, never by editing the config (tenant hooks block that path). `add` checks forum + bot admin with Manage Topics (prints the fix otherwise), rewrites only `owner_groups`, restarts (from a bot run: deferred). Idempotent.
- In those groups only the owner is heard (+ Peer bots below); anyone else, other bots, anonymous admins are ignored. Every topic is its own session, like in the private chat. A group not in `owner_groups`: the bot stays if the owner added it (logs its id), else leaves.
- `spawn` / `send` / `alive` / `topic-icon` / `notify` / `notify-delete` take `--chat NAME|ID`; default = the private chat. A `t.me/c/<chat>/<thread>` link carries its chat, so `--thread LINK` needs no `--chat`. Runs get `CLAUDE_TG_RUN_CHAT` next to `CLAUDE_TG_RUN_TOPIC`: `notify` and `restart` reports from inside a run go back to its own chat.
- Group limits apply there (no drafts, ~20 msg/min).

## Peer bots (two bots talking in one group)

- When: another bot (someone else's Claude bot) shares a group with ours and they should talk. Works in group mode and owner groups.
- Enable: BotFather: turn Bot-to-Bot Communication Mode on for our bot (Telegram delivers bot messages only if one of the two bots has it); then `claude-tg bots add <id|@name>` (never edit the config; `@name` only once the logs show `ignored: bot ID (@name)`). `doctor` lists `allowed_bots`.
- Heard only when the peer addresses us: a reply to our message, `/cmd@ourbot`, or `@ourbot` in text. Telegram itself delivers only the first two, unless our bot is admin + privacy mode off; a peer's `/cmd` is a prompt, never a bot command. Other bots: ignored.
- Our answer to a peer goes out as a reply to its message (the only form it surely receives). The prompt tags it `[From bot: Name (@user, id N) …]`.
- Loop guard: config `bot_turns_max` (default 6, 0 = off) bot messages in a row per topic with no human between; then bots are ignored there until a human writes, one 🔁 note. In memory: a restart resets the counts.

## Who a group message is for (group mode, owner groups)

- A person's admitted message in a group topic runs claude only when it is for the bot: an `@ourbot` / text mention / `/cmd`; a reply to our message that mentions no one else; or a bare message (no reply, no mention) right after our last message. A reply to someone else, a message mentioning only others, or a bare message after someone else spoke (a person, another bot, heard or not) is theirs: no 👀, no run, one `is for someone else` log line.
- A bare message after the sender's own keeps that message's verdict (bursts, albums, forwards). Nobody seen yet in the topic (fresh start): ours.
- History: the last 20 speakers per topic, in memory (a restart forgets). Others' messages are seen only when the bot is admin (privacy off); otherwise the rule degrades to the old behavior.
