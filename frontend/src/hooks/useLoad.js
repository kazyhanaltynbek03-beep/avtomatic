import { useEffect, useState } from "react";
import { api } from "../services/api";

export function useLoad(path, refresh) {
  const [state, setState] = useState(() => ({ loading: Boolean(path) }));

  useEffect(() => {
    let live = true;
    const controller = new globalThis.AbortController();
    if (!path) {
      setState({ data: null });
      return () => { live = false; };
    }
    setState({ loading: true });
    api(path, { signal: controller.signal })
      .then((data) => { if (live) setState({ data }); })
      .catch((error) => { if (live) setState({ error: error.message }); });
    return () => { live = false; controller.abort(); };
  }, [path, refresh]);

  return state;
}
