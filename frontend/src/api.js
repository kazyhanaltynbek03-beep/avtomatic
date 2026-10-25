let csrf = "";
export function setCsrf(value) {
  csrf = value || "";
}
export async function api(path, options = {}) {
  const isForm = options.body instanceof FormData;
  const res = await fetch("/api" + path, {
    credentials: "same-origin",
    ...options,
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
  if (!res.ok)
    throw new Error(
      typeof data.detail === "string"
        ? data.detail
        : (data.detail?.message || JSON.stringify(data.detail || "Ошибка запроса")),
    );
  return data;
}
export const money = (n) =>
  n == null
    ? "—"
    : new Intl.NumberFormat("ru-RU", {
        style: "currency",
        currency: "KZT",
        maximumFractionDigits: 0,
      })
        .format(n / 100)
        .replace("KZT", "₸");
export const decimal = (n) =>
  n == null
    ? "—"
    : new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 2 }).format(n);
export const today = () =>
  new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Almaty",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date());
export const can = (auth, c, write = false) =>
  auth?.permissions?.includes("*") ||
  auth?.permissions?.includes(c) ||
  (!write && auth?.permissions?.includes(c + ":read"));
