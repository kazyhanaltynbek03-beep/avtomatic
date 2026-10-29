import React from "react";
import { createRoot } from "react-dom/client";
import App from "./app/Workspace";
import { AppErrorBoundary } from "./components/Feedback";
import "./qor-redesign.css";

createRoot(document.getElementById("root")).render(
  <AppErrorBoundary>
    <App />
  </AppErrorBoundary>,
);
