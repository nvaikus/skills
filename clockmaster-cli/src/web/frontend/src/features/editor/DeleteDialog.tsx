import { useState } from "react";
import type { TaskDetail } from "../../lib/types";
import { deleteTask } from "../../data/actions";
import { errorText } from "../../data/api";
import { Button } from "../../ui/Button";
import { Dialog } from "../../ui/Dialog";
import { ErrorText } from "../../ui/Feedback";
import { Checkbox } from "../../ui/Field";
import { useToast } from "../../ui/Toast";

export function DeleteDialog({ task, onClose, onDeleted }: { task: TaskDetail; onClose: () => void; onDeleted: () => void }) {
  const [purge, setPurge] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const toast = useToast();
  const go = async () => {
    setBusy(true);
    setErr(null);
    try {
      const r = await deleteTask(task.name, purge);
      toast("ok", `Deleted ${task.name}${r.purgedRuns ? " and its run history" : ""}`);
      onDeleted();
    } catch (e) {
      setErr(errorText(e));
      setBusy(false);
    }
  };
  return (
    <Dialog
      open
      width="sm"
      onClose={onClose}
      title={`Delete ${task.name}?`}
      footer={
        <>
          <Button variant="ghost" onClick={onClose} data-autofocus>
            Cancel
          </Button>
          <Button variant="danger" icon="trash" busy={busy} onClick={go}>
            Delete
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-4 text-body text-fg-2">
        <p>The task stops running and its file is removed. This can't be undone.</p>
        <Checkbox checked={purge} onChange={setPurge}>
          Also delete its run history and logs
          <span className="block text-caption text-fg-3">Otherwise past runs are kept on disk.</span>
        </Checkbox>
        {err && <ErrorText>{err}</ErrorText>}
      </div>
    </Dialog>
  );
}
