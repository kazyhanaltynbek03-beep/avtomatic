export const money = (n) =>
  n == null
    ? "—"
    : new Intl.NumberFormat("ru-RU", {
        style: "currency",
        currency: "KZT",
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
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
