import { useCallback, useEffect, useState } from "react";
import { parseRoute, routeHash, type Route } from "../lib/route";
import { onHashChange, readHash, setHash } from "../platform/web/location";

export function useRoute() {
  const [route, setRoute] = useState<Route>(() => parseRoute(readHash()));
  useEffect(() => onHashChange(() => setRoute(parseRoute(readHash()))), []);
  const go = useCallback((r: Route, mode: "push" | "replace" = "push") => setHash(routeHash(r), mode), []);
  return { route, go };
}
