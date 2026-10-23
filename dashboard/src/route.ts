import { useSyncExternalStore } from "react";

export type Route =
  | { page: "queue" }
  | { page: "claim"; claimId: string }
  | { page: "instructions" };

export function routeOf(hash: string): Route {
  const claim = /^#\/claims\/([^/]+)$/.exec(hash);
  if (claim?.[1])
    return { page: "claim", claimId: decodeURIComponent(claim[1]) };
  if (hash === "#/instructions") return { page: "instructions" };
  return { page: "queue" };
}

function subscribe(onChange: () => void): () => void {
  window.addEventListener("hashchange", onChange);
  return () => {
    window.removeEventListener("hashchange", onChange);
  };
}

export function useRoute(): Route {
  const hash = useSyncExternalStore(subscribe, () => window.location.hash);
  return routeOf(hash);
}
