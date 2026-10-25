import { useEffect, useState } from "react";
import { api } from "../services/api";

export function useLoad(path, refresh) {
  const [state, setState] = useState(() => ({ loading: Boolean(path) }));

  useEffect(() => {
    let live = true;
    if (!path) {
      setState({ data: null });
      return () => { live = false; };
    }
    setState({ loading: true });
    api(path)
      .then((data) => { if (live) setState({ data }); })
      .catch((error) => { if (live) setState({ error: error.message }); });
    return () => { live = false; };
  }, [path, refresh]);

  return state;
}
