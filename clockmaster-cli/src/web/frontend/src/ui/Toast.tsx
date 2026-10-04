import { createContext, useCallback, useContext, useState, type ReactNode } from "react";
import { Icon } from "./Icon";

type Kind = "info" | "ok" | "error";
interface Toast {
  id: number;
  kind: Kind;
  text: string;
  detail?: string;
}

const Ctx = createContext<(kind: Kind, text: string, detail?: string) => void>(() => {});
export const useToast = () => useContext(Ctx);

let seq = 0;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [list, setList] = useState<Toast[]>([]);
  const push = useCallback((kind: Kind, text: string, detail?: string) => {
    const id = ++seq;
    setList((l) => [...l.slice(-3), { id, kind, text, detail }]);
    setTimeout(() => setList((l) => l.filter((t) => t.id !== id)), kind === "error" ? 8000 : 3500);
  }, []);
  return (
    <Ctx.Provider value={push}>
      {children}
      <div aria-live="polite" className="pointer-events-none fixed inset-x-0 bottom-0 z-(--z-toast) flex flex-col items-center gap-2 p-4 pb-[max(1rem,env(safe-area-inset-bottom))]">
        {list.map((t) => (
          <div key={t.id} role={t.kind === "error" ? "alert" : "status"} className="pointer-events-auto flex max-w-md animate-rise items-start gap-2.5 rounded-xl border border-line bg-surface px-3.5 py-2.5 text-body text-fg-1 shadow-xl">
            <Icon name={t.kind === "error" ? "alert" : t.kind === "ok" ? "check" : "info"} size={15} className={`mt-0.5 ${t.kind === "error" ? "text-fail" : t.kind === "ok" ? "text-ok" : "text-fg-3"}`} />
            <div className="min-w-0">
              <div>{t.text}</div>
              {t.detail && <pre className="mt-1 max-h-32 overflow-auto whitespace-pre-wrap font-mono text-micro text-fg-3">{t.detail}</pre>}
            </div>
          </div>
        ))}
      </div>
    </Ctx.Provider>
  );
}
