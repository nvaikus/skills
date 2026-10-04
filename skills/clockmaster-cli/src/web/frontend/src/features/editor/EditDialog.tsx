import { useState } from "react";
import type { EditForm, TaskDetail } from "../../lib/types";
import { changedKeys, formOf, formProblems } from "../../lib/edit";
import { editTask } from "../../data/actions";
import { errorText } from "../../data/api";
import { Button } from "../../ui/Button";
import { Dialog } from "../../ui/Dialog";
import { ErrorText } from "../../ui/Feedback";
import { TextField } from "../../ui/Field";
import { useToast } from "../../ui/Toast";
import { ScheduleField } from "./ScheduleField";

/**
 * Mount with a key per open: the form is a snapshot of the task taken ONCE, so
 * background polling never overwrites what the user is typing, and only the
 * keys the user changed are sent.
 */
/** `focus`: the field to start in (a settings chip on the task page opens the editor there). */
export function EditDialog({ task, focus = "name", onClose, onSaved }: { task: TaskDetail; focus?: keyof EditForm; onClose: () => void; onSaved: (oldName: string, newName: string) => void }) {
  const [orig] = useState(() => formOf(task));
  const [f, setF] = useState<EditForm>(orig);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [tried, setTried] = useState(false);
  const toast = useToast();
  const cur = f;
  const problems = formProblems(cur);
  const diff = changedKeys(orig, cur);
  const dirty = Object.keys(diff).length > 0;
  const set = (k: keyof EditForm) => (v: string) => setF((x) => ({ ...x, [k]: v }));
  const show = (k: keyof EditForm) => (tried || cur[k] !== orig[k] ? problems[k] : undefined);

  const save = async () => {
    setTried(true);
    if (Object.keys(problems).length) return;
    if (!dirty) return onClose();
    setBusy(true);
    setErr(null);
    try {
      const r = await editTask(task.name, diff);
      toast("ok", r.name !== task.name ? `Renamed to ${r.name}` : "Saved", r.syncOutput || undefined);
      onSaved(task.name, r.name);
    } catch (e) {
      setErr(errorText(e));
      setBusy(false);
    }
  };

  return (
    <Dialog
      open
      onClose={onClose}
      width="lg"
      title={`Edit ${task.name}`}
      subtitle="Changes are saved to the task file and applied to the system scheduler."
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" busy={busy} disabled={!dirty} onClick={save}>
            Save
          </Button>
        </>
      }
    >
      <form
        className="flex flex-col gap-4"
        onSubmit={(e) => {
          e.preventDefault();
          void save();
        }}
      >
        <div className="grid gap-4 sm:grid-cols-2">
          <TextField label="Name" value={f.name} onChange={set("name")} error={show("name")} hint={f.name !== orig.name ? "Renaming keeps the run history." : "Lowercase, dashes allowed."} autoFocus={focus === "name"} />
          <TextField label="Group" value={f.group} onChange={set("group")} error={show("group")} placeholder="none" hint="Tasks with the same group are listed together." />
        </div>
        <TextField label="Description" value={f.description} onChange={set("description")} placeholder="What this task is for" />
        <ScheduleField value={f.schedule} onChange={set("schedule")} problem={show("schedule")} autoFocus={focus === "schedule"} />
        <TextField label="Command" mono multiline value={f.command} onChange={set("command")} error={show("command")} autoFocus={focus === "command"} />
        <TextField label="Folder" mono value={f.workdir} onChange={set("workdir")} placeholder="~" hint="Where the command runs. Blank = home folder." autoFocus={focus === "workdir"} />
        <div className="grid gap-4 sm:grid-cols-2">
          <TextField label="Time limit" value={f.timeout} onChange={set("timeout")} placeholder="2h" hint="e.g. 90s, 30m, 2h or none. Blank = 2h." autoFocus={focus === "timeout"} />
          <TextField label="Runs to keep" value={f.keep} onChange={set("keep")} placeholder="250" hint="A number or unlimited. Blank = 250." autoFocus={focus === "keep"} />
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <TextField label="Runs at once" value={f.parallel} onChange={set("parallel")} error={show("parallel")} placeholder="1" hint="Runs of this task at the same time. Blank = 1." autoFocus={focus === "parallel"} />
          <TextField label="Queue size" value={f.queue} onChange={set("queue")} error={show("queue")} placeholder="20" hint="Runs that may wait; one more is skipped. Blank = 20." autoFocus={focus === "queue"} />
        </div>
        {err && <ErrorText>{err}</ErrorText>}
        <button type="submit" hidden />
      </form>
    </Dialog>
  );
}
