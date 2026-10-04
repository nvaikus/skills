import type { ThemePref } from "../platform/web/theme";
import { Button, IconButton } from "../ui/Button";
import { Icon } from "../ui/Icon";
import { MenuItem, Popover } from "../ui/Popover";

const THEMES: { value: ThemePref; label: string; icon: "monitor" | "sun" | "moon" }[] = [
  { value: "light", label: "Light", icon: "sun" },
  { value: "dark", label: "Dark", icon: "moon" },
  { value: "system", label: "Match device", icon: "monitor" },
];

export function Header({ title, drift, syncing, onSync, theme, dark, onTheme, onHome }: { title: string; drift: number; syncing: boolean; onSync: () => void; theme: ThemePref; dark: boolean; onTheme: (t: ThemePref) => void; onHome: () => void }) {
  // the trigger shows the theme actually on screen, even when it follows the device
  const shown = dark ? "dark" : "light";
  const themeLabel = theme === "system" ? `Theme: Match device (${shown})` : `Theme: ${shown === "dark" ? "Dark" : "Light"}`;
  return (
    <header className="sticky top-0 z-(--z-sticky) border-b border-line-soft bg-canvas/85 backdrop-blur-md pt-[env(safe-area-inset-top)]">
      <div className="flex h-14 items-center gap-3 px-3 sm:px-6 lg:px-8">
        <a href="#/" onClick={(e) => (e.preventDefault(), onHome())} className="flex min-w-0 items-center gap-2.5 rounded-lg">
          <span className="grid size-8 shrink-0 place-items-center rounded-xl bg-fg-1 text-canvas">
            <Icon name="clock" size={17} />
          </span>
          <span className="min-w-0">
            <span className="block truncate text-title font-semibold tracking-tight">{title}</span>
          </span>
        </a>
        <div className="ml-auto flex items-center gap-1.5">
          {drift > 0 && (
            <Button size="sm" icon="sync" busy={syncing} onClick={onSync}>
              <span className="text-warn">{drift}<span className="hidden sm:inline"> out of sync</span></span> · Sync
            </Button>
          )}
          <Popover
            width="w-44"
            trigger={({ open, toggle }) => <IconButton icon={dark ? "moon" : "sun"} label={themeLabel} active={open} onClick={toggle} aria-haspopup="menu" aria-expanded={open} />}
          >
            {(close) =>
              THEMES.map((t) => (
                <MenuItem key={t.value} icon={t.icon} checked={t.value === theme} onSelect={() => (close(), onTheme(t.value))}>
                  {t.label}
                </MenuItem>
              ))
            }
          </Popover>
        </div>
      </div>
    </header>
  );
}
