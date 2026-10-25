let csrf = "";

export function setCsrf(value) {
  csrf = value || "";
}

function messageFromResponse(data) {
  if (typeof data?.detail === "string") return data.detail;
  if (typeof data?.message === "string") return data.message;
  if (typeof data?.detail?.message === "string") return data.detail.message;
  return "Не удалось выполнить запрос. Повторите попытку.";
}

export async function api(path, options = {}) {
  const { timeoutMs = 45000, signal: callerSignal, ...requestOptions } = options;
  const isForm = options.body instanceof FormData;
  const controller = new globalThis.AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  const abortFromCaller = () => controller.abort();
  callerSignal?.addEventListener("abort", abortFromCaller, { once: true });
  if (callerSignal?.aborted) controller.abort();
  try {
    const res = await fetch("/api" + path, {
      credentials: "same-origin",
      ...requestOptions,
      signal: controller.signal,
      headers: {
        ...(isForm ? {} : { "Content-Type": "application/json" }),
        "X-CSRF-Token": csrf,
        ...options.headers,
      },
      body: options.body
        ? isForm
          ? options.body
          : JSON.stringify(options.body)
        : undefined,
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(messageFromResponse(data));
    return data;
  } catch (error) {
    if (error?.name === "AbortError") throw new Error("Время ожидания истекло. Проверьте соединение и повторите.");
    throw error;
  } finally {
    clearTimeout(timer);
    callerSignal?.removeEventListener("abort", abortFromCaller);
  }
}

// Download protected binary reports with the same session cookie as JSON API calls.
export async function downloadApiFile(path, fallbackName = "report.xlsx") {
  const controller = new globalThis.AbortController();
  const timer = setTimeout(() => controller.abort(), 90000);
  try {
    const response = await fetch("/api" + path, {
      method: "GET",
      credentials: "same-origin",
      headers: { "X-CSRF-Token": csrf },
      signal: controller.signal,
    });
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      if (response.status === 401) {
        throw new Error("Сессия истекла или вход не выполнен. Войдите в QOR заново и повторите скачивание.");
      }
      throw new Error(messageFromResponse(data));
    }
    const blob = await response.blob();
    if (!blob.size) throw new Error("Сервер вернул пустой Excel-файл.");
    const disposition = response.headers.get("Content-Disposition") || "";
    const filename = disposition.match(/filename="?([^";]+)"?/i)?.[1] || fallbackName;
    const url = globalThis.URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    try {
      anchor.href = url;
      anchor.download = filename;
      document.body.appendChild(anchor);
      anchor.click();
    } finally {
      anchor.remove();
      setTimeout(() => globalThis.URL.revokeObjectURL(url), 1000);
    }
  } catch (error) {
    if (error?.name === "AbortError") throw new Error("Превышено время ожидания скачивания Excel.");
    throw error;
  } finally {
    clearTimeout(timer);
  }
}
