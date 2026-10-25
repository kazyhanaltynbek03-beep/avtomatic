import React from "react";
import { AlertCircle, LoaderCircle, Package } from "lucide-react";

export class AppErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { failed: false };
  }

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch(error) {
    // Keep the user-facing surface safe; detailed observability remains server-side.
    console.error("QOR UI error", error);
  }

  render() {
    if (this.state.failed) {
      return (
        <main className="fatal-error">
          <h1>Не удалось открыть часть QOR</h1>
          <p>Данные не были изменены. Обновите страницу; если ошибка повторится, обратитесь к администратору.</p>
          <button className="primary" onClick={() => window.location.reload()}>Обновить страницу</button>
        </main>
      );
    }
    return this.props.children;
  }
}

export function ErrorBox({ error }) {
  return error ? (
    <div className="error" role="alert">
      <AlertCircle size={18} />
      {error}
    </div>
  ) : null;
}

export function Empty({ text = "Пока нет записей. Добавьте первый документ или импортируйте данные." }) {
  return <div className="empty"><Package size={30} /><p>{text}</p></div>;
}

export function Spinner() {
  return <div className="loading"><LoaderCircle className="spin" size={22} /> Загрузка данных…</div>;
}
