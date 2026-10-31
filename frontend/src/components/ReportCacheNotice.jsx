import { useEffect, useState } from "react";

export function ReportCacheNotice() {
  const [states, setStates] = useState({});

  useEffect(() => {
    const update = (event) => {
      const { key, status } = event.detail || {};
      if (!key) return;
      setStates((current) => {
        if (status === "clear") {
          const next = { ...current };
          delete next[key];
          return next;
        }
        return { ...current, [key]: status };
      });
    };
    window.addEventListener("qor-report-cache-state", update);
    return () => window.removeEventListener("qor-report-cache-state", update);
  }, []);

  const statuses = Object.values(states);
  if (!statuses.length) return null;
  const failed = statuses.includes("error");
  return (
    <div
      role="status"
      aria-live="polite"
      style={{
        position: "fixed",
        zIndex: 10000,
        top: 88,
        left: "50%",
        transform: "translateX(-50%)",
        width: "min(560px, calc(100% - 28px))",
        padding: "10px 14px",
        border: "1px solid #dce8e1",
        borderRadius: 12,
        background: "#fff",
        color: "#375449",
        boxShadow: "0 8px 24px rgba(20, 40, 34, .12)",
        fontSize: 14,
      }}
    >
      {failed
        ? "Показаны сохранённые данные. Не удалось обновить отчёт."
        : "Показаны сохранённые данные. Обновляем отчёт…"}
    </div>
  );
}
