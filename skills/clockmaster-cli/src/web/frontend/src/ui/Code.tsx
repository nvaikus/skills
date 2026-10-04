import { useState } from "react";
import { copyText } from "../platform/web/dom";
import { IconButton } from "./Button";
import { tipIfCut } from "./Tooltip";

/** A copyable one-liner (command, cron, path). */
export function CodeLine({ text, label = "Copy" }: { text: string; label?: string }) {
  const [done, setDone] = useState(false);
  return (
    <div className="flex items-center gap-1 rounded-lg border border-line bg-sunken py-1 pr-1 pl-3">
      <code className="min-w-0 flex-1 overflow-x-auto whitespace-pre font-mono text-caption text-fg-1">{text}</code>
      <IconButton
        icon={done ? "check" : "copy"}
        label={done ? "Copied" : label}
        size="sm"
        onClick={async () => {
          if (await copyText(text)) {
            setDone(true);
            setTimeout(() => setDone(false), 1500);
          }
        }}
      />
    </div>
  );
}

/** A value shown as monospace text on one line (ellipsis), with a copy button. */
export function CodeValue({ text, label = "Copy" }: { text: string; label?: string }) {
  const [done, setDone] = useState(false);
  return (
    <span className="flex min-w-0 items-center gap-1">
      <code {...tipIfCut(text)} className="min-w-0 flex-1 truncate font-mono text-caption text-fg-1">
        {text}
      </code>
      <IconButton
        icon={done ? "check" : "copy"}
        label={done ? "Copied" : label}
        size="sm"
        onClick={async () => {
          if (await copyText(text)) {
            setDone(true);
            setTimeout(() => setDone(false), 1500);
          }
        }}
      />
    </span>
  );
}
