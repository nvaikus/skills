import { useEffect, useState } from "react";
import { applyThemePref, onSystemThemeChange, readThemePref, systemDark, type ThemePref } from "../platform/web/theme";

export function useTheme() {
  const [pref, setPref] = useState<ThemePref>(readThemePref);
  const [sysDark, setSysDark] = useState(systemDark);
  useEffect(() => applyThemePref(pref), [pref]);
  useEffect(() => onSystemThemeChange(() => setSysDark(systemDark())), []);
  return { pref, setPref, dark: pref === "dark" || (pref === "system" && sysDark) };
}
