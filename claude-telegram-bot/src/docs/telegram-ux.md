# Telegram UX: topics, drafts, status message, bursts

Read when touching topic handling, drafts, the status message, the ⏹ button, message debouncing, bot-facing text or the bot profile.

- Private-chat topics: the first message of a user-created topic carries `reply_to_message.forum_topic_created` (`is_name_implicit` → we may rename). `createForumTopic` / `editForumTopic` work in private chats.
- `sendMessageDraft`: ephemeral 30 s preview, replaced by the next real message; `can_stop` adds a stop button → `stopped_message_generation` update with `draft_id`. Any non-429 failure flips the bridge to edit-message streaming for the process lifetime.
- Deleting a topic in the client produces no update; send errors `message thread not found` / `TOPIC_*` → `Bridge.forget`. `Store.drop` blocks later writes so a finishing run can't resurrect it.
- The status message carries an inline ⏹ (`callback_data: stop`) → `Bridge.button` stops the run whose `st.id` matches, queue kept. Every `editMessageText` must resend `reply_markup`, or the keyboard disappears.
- `Status` renders from a 0.5 s ticker thread (elapsed time moves while a tool runs silently); the event loop only sets attributes. Request budget: friendly edits at once on phase/memo change, timer-only ≥ `MIN_EDIT` 10 s (timer steps 15 s/30 s/1 min); detailed ≤ 1 edit per `VERBOSE_EDIT` 6 s. Typing: once at turn start, then only while `Worker.shows_progress` is false. Once shown, it is edited in place, never re-sent: a new message would wipe the `sendMessageDraft` preview.
- Forward-with-comment = comment, then each forward as separate updates < 1 s apart (albums: N updates). `Bridge.collect` debounces per topic (`BURST` 1 s, `ALBUM` 1.5 s, `FORWARD` 6 s - a forwarded photo came 5 s after its text) → one run; a burst in All messages gets one `new_topic` at flush.
- New bot-facing text → a key in both `ui.S` tables (a test checks key/placeholder parity).
- `setMyProfilePhoto` takes `photo` = InputProfilePhoto JSON `{"type":"static","photo":"attach://p"}` + the jpg as multipart field `p` (jpg only: `botprofile` converts via ffmpeg).
