# Owner groups, peer bots, group mode, addressing

Read when touching chat admission (`Bridge.admits` / `owner_admits` / `peer_ok` / `general_ok`), topic keys, `general.py`, `groups.py`, `peerbots.py`, or how answers address people.

- Owner groups (private mode, config `owner_groups` name → id): `Bridge.owner_admits` = configured chat + owner only. Store/worker/pending keys come from `config.topic_key` / `Worker.pk`: home chat (private or `group_id`) = plain thread / message id (no migration), owner group = `"<chat>:<id>"` (ids repeat across chats). Runs get `CLAUDE_TG_RUN_CHAT`; `/proc` liveness, `notify` default, `restart --report chat:thread` use it. CLI chat: `inbox.target_chat` (`--chat` > `t.me/c/` link > home). `notify.json` caches owner-group topics under `chats.<id>`. Drafts only when `chat > 0`.
- Peer bots (config `allowed_bots`, both group kinds): `Bridge.peer_ok` = listed + `general.mentions` (reply to us, @us, `/cmd@us`, text mention); `bot_gate` (before the General filter) counts admitted bot messages per topic key, a human one resets, > `bot_turns_max` dropped + one `bot_loop` note (memory only). A bot's `/...` never reaches `command`. `Worker.reply_to` (set on the replay `user` event via `bot_target`) makes the next answer's first chunk a reply: Telegram delivers a bot only replies to it / `/cmd@it` (plain @mention only with admin + privacy off).

## Group mode (`group_id` set)

- Admission: `Bridge.admits` = that chat + `allowed_users` (+ peer bots), no `sender_chat`/other bots; owner lock unused.
- Topic = `message_thread_id` only with `is_topic_message` (replies in General carry a thread id too). `GROUP_SERVICE` messages skipped.
- General (both group kinds) dropped by `Bridge.general_ok` unless `group_general`; meanwhile `Bridge.general_mention` buffers admitted senders' messages (`general.Buffer`, `STATE_DIR/general.json`, last `general_context`) and lets a bot mention / reply to the bot through, marked `_mention` + `_context` (rendered block, kept in pending) → `flush` → `new_topic` (seed without @bot) + `general_link` reply; `Worker.prompt` puts `_context` first; rename titles `general.title_part`.
- `notify.owner_chat` returns the group: every CLI destination follows. Link `t.me/c/<id w/o -100>/<thread>/<msg>`.
- No `sendMessageDraft` in groups (`draft_ok` False from start). ~20 msg/min per group: `Flood.limits` gives chats with negative ids `GROUP_RATE`/`GROUP_BURST`.
- Admin bot sees all messages; non-admin with privacy mode only commands (`doctor` checks). `chats` = getUpdates without offset (confirms nothing).

## Addressing

- `notify.people` (group: allowed_users / private: owner, cached `member:<chat>:<uid>`) → `people_prompt` appended to `--append-system-prompt` in `execute`, `address` rewrites `Name:` headers in `send_answer`. Lookup failures = [] (never block a run). `fmt.md_to_html` passes `tg://user?id=N` links (text mention).
