"""Bot-facing strings (one table per `ui_lang`) and the friendly status line. Pure: no I/O."""

LANGS = ("en", "ru")

# tool name -> phase key; unknown tools and MCP tools fall back to "work"
TOOL_PHASE = {
    "Read": "read", "Glob": "search", "Grep": "search", "LS": "read",
    "Bash": "work", "BashOutput": "work", "KillShell": "work",
    "Edit": "edit", "MultiEdit": "edit", "Write": "edit", "NotebookEdit": "edit",
    "WebSearch": "web", "WebFetch": "web",
    "Task": "agent", "Agent": "agent",
    "TodoWrite": "plan",
}

S = {
    "en": {
        "ph.think": "🧠 Thinking…", "ph.read": "📖 Reading files…", "ph.search": "🔎 Searching…",
        "ph.work": "⚙️ Working…", "ph.edit": "✏️ Making changes…", "ph.web": "🌐 Searching the web…",
        "ph.agent": "👥 Bringing in a helper…", "ph.plan": "📝 Making a plan…", "ph.write": "✍️ Writing the answer…",
        "sec": "{s} s", "min": "{m} min {s} s",
        "help": "Each topic is its own Claude Code session. Write in a topic (or in All messages: a new topic is "
                "created). Photos, files and voice notes work.\n\n"
                "/cd <path> - working directory (starts a new session)\n/new - new session\n"
                "/stop - stop the running task\n/status - session info\n"
                "/verbose - detailed progress (tool calls) on/off\n"
                "/rename <title> - rename the topic\n/delete - delete the topic (the Claude session file stays on disk)",
        "cmd.new": "Start a new Claude session in this topic", "cmd.stop": "Stop the running Claude in this topic",
        "cmd.status": "Session, cwd, running?", "cmd.cd": "Set working directory: /cd <path>",
        "cmd.verbose": "Detailed progress on/off", "cmd.rename": "Rename this topic: /rename <title>",
        "cmd.delete": "Delete this topic and forget its session", "cmd.help": "How this bot works",
        "in_topic": "/{cmd} works inside a topic.",
        "write_in_topic": "Please write inside a topic: each topic is a separate Claude session.",
        "rename_usage": "Usage: /rename <title>", "rename_fail": "😕 Could not rename: {e}",
        "delete_fail": "😕 Could not delete: {e}",
        "new": "🆕 New session from the next message. Folder: {cwd}",
        "stopped": "⏹ Stopped.", "stopped_n": "⏹ Stopped, dropped {n} queued.", "idle": "Nothing is running.",
        "status": "session: {sid}\nfolder: {cwd}\nrunning: {run}\ntitle: {title}\ndetailed progress: {verbose}",
        "yes": "yes", "no": "no", "new_next": "(new on next message)", "queued": ", queued: {n}", "bg": ", background tasks: {n}",
        "cd_show": "Folder: {cwd}\nUsage: /cd <path>", "cd_bad": "😕 Not a folder: {path}",
        "cd_ok": "📁 Folder: {path}\nA new session starts with the next message.",
        "verbose_on": "🔍 Detailed progress on: tool calls are shown.",
        "verbose_off": "✨ Detailed progress off: short status only.",
        "restart_rerun": "↻ The bot restarted mid-run - running this message again.",
        "restart_resend": "⚠️ The bot restarted and this message was not answered. Please resend it.",
        "restart_ok": "♻️ Bot restarted: {rev}",
        "restart_down": "💔 Bot restarted but is not running ({state}). Fix it over SSH: `claude-tg logs`.",
        "restart_busy": "⚠️ Restart skipped: the bot was still busy after {s} s.",
        "session_lost": "(previous session not found - started a new one)",
        "empty": "(empty answer)", "more_parts": "… {n} more parts in answer.md",
        "err": "😕 Something went wrong: {why}",
        "denied": "🚫 Not allowed in auto mode: {tool}",
        "leak": "🔒 Answer hidden: it contained internal materials.",
        "leak_file": "🔒 File not sent: it contains internal materials.",
        "why.no_result": "Claude stopped without an answer.", "why.claude": "Claude reported an error.",
        "why.bridge": "internal bot error.", "why.download": "could not download the attachment.",
        "why.stt_missing": "voice notes need the model-cli skill (github.com/nvaikus/skills/tree/main/model-cli).",
        "why.stt_failed": "could not transcribe the voice note.",
    },
    "ru": {
        "ph.think": "🧠 Думаю…", "ph.read": "📖 Изучаю файлы…", "ph.search": "🔎 Ищу…",
        "ph.work": "⚙️ Работаю…", "ph.edit": "✏️ Вношу правки…", "ph.web": "🌐 Ищу в интернете…",
        "ph.agent": "👥 Подключаю помощника…", "ph.plan": "📝 Составляю план…", "ph.write": "✍️ Пишу ответ…",
        "sec": "{s} с", "min": "{m} мин {s} с",
        "help": "Каждая тема - отдельная сессия Claude Code. Пишите в теме (или во «Всех сообщениях» - тогда "
                "создастся новая тема). Можно слать фото, файлы и голосовые.\n\n"
                "/cd <путь> - рабочая папка (начинает новую сессию)\n/new - новая сессия\n"
                "/stop - остановить текущую задачу\n/status - информация о сессии\n"
                "/verbose - подробный ход работы вкл/выкл\n"
                "/rename <название> - переименовать тему\n/delete - удалить тему (файл сессии Claude останется)",
        "cmd.new": "Новая сессия Claude в этой теме", "cmd.stop": "Остановить Claude в этой теме",
        "cmd.status": "Сессия, папка, идёт ли работа", "cmd.cd": "Рабочая папка: /cd <путь>",
        "cmd.verbose": "Подробный ход работы вкл/выкл", "cmd.rename": "Переименовать тему: /rename <название>",
        "cmd.delete": "Удалить тему и забыть сессию", "cmd.help": "Как работает бот",
        "in_topic": "/{cmd} работает внутри темы.",
        "write_in_topic": "Пишите, пожалуйста, внутри темы: каждая тема - отдельная сессия Claude.",
        "rename_usage": "Так: /rename <название>", "rename_fail": "😕 Не удалось переименовать: {e}",
        "delete_fail": "😕 Не удалось удалить: {e}",
        "new": "🆕 Со следующего сообщения - новая сессия. Папка: {cwd}",
        "stopped": "⏹ Остановлено.", "stopped_n": "⏹ Остановлено, убрано из очереди: {n}.",
        "idle": "Сейчас ничего не выполняется.",
        "status": "сессия: {sid}\nпапка: {cwd}\nработает: {run}\nназвание: {title}\nподробный режим: {verbose}",
        "yes": "да", "no": "нет", "new_next": "(новая со следующего сообщения)", "queued": ", в очереди: {n}", "bg": ", фоновых задач: {n}",
        "cd_show": "Папка: {cwd}\nТак: /cd <путь>", "cd_bad": "😕 Это не папка: {path}",
        "cd_ok": "📁 Папка: {path}\nСо следующего сообщения начнётся новая сессия.",
        "verbose_on": "🔍 Подробный режим включён: видны все шаги.",
        "verbose_off": "✨ Подробный режим выключен: только короткий статус.",
        "restart_rerun": "↻ Бот перезапустился во время ответа - выполняю это сообщение заново.",
        "restart_resend": "⚠️ Бот перезапустился, и на это сообщение не ответил. Пришлите его ещё раз.",
        "restart_ok": "♻️ Бот перезапущен: {rev}",
        "restart_down": "💔 Бот перезапущен, но не работает ({state}). Чинить по SSH: `claude-tg logs`.",
        "restart_busy": "⚠️ Перезапуск отменён: бот был занят дольше {s} с.",
        "session_lost": "(прошлая сессия не нашлась - начал новую)",
        "empty": "(пустой ответ)", "more_parts": "… ещё частей: {n}, всё целиком в answer.md",
        "err": "😕 Не получилось: {why}",
        "denied": "🚫 Авторежим не разрешил: {tool}",
        "leak": "🔒 Ответ скрыт: в нём были внутренние материалы.",
        "leak_file": "🔒 Файл не отправлен: в нём внутренние материалы.",
        "why.no_result": "Claude остановился, не дав ответа.", "why.claude": "Claude сообщил об ошибке.",
        "why.bridge": "внутренняя ошибка бота.", "why.download": "не удалось скачать вложение.",
        "why.stt_missing": "для голосовых нужен скилл model-cli (github.com/nvaikus/skills/tree/main/model-cli).",
        "why.stt_failed": "не удалось распознать голосовое.",
    },
}


def lang(cfg: dict) -> str:
    v = (cfg.get("ui_lang") or "en").lower()
    return v if v in LANGS else "en"


def t(lng: str, key: str, **kw) -> str:
    s = S.get(lng, S["en"]).get(key) or S["en"][key]
    return s.format(**kw) if kw else s


def tool_phase(name: str) -> str:
    return TOOL_PHASE.get(name or "", "work")


def elapsed(lng: str, sec: float) -> str:
    """Rounded down to 5 s so the line changes (and is edited) at most every 5 s."""
    s = int(sec) // 5 * 5
    return t(lng, "sec", s=s) if s < 60 else t(lng, "min", m=s // 60, s=s % 60)


def status_line(lng: str, phase: str, sec: float, show_after: float = 10.0) -> str:
    """One short line: phase phrase + a subtle elapsed time once the run takes a while."""
    line = t(lng, "ph." + phase)
    return f"{line} · {elapsed(lng, sec)}" if sec >= show_after else line


def reason(text: str, n: int = 160) -> str:
    """First meaningful line of an error, shortened - the full text goes to logs / verbose mode."""
    line = next((x.strip() for x in (text or "").splitlines() if x.strip()), "")
    return line if len(line) <= n else line[: n - 1] + "…"
