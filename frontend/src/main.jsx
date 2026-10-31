import React from "react";
import { createRoot } from "react-dom/client";
import App from "./app/Workspace";
import { AppErrorBoundary } from "./components/Feedback";
import { ReportCacheNotice } from "./components/ReportCacheNotice";
import "./qor-redesign.css";
import "./visual-reference.css";

createRoot(document.getElementById("root")).render(
  <AppErrorBoundary>
    <App />
    <ReportCacheNotice />
  </AppErrorBoundary>,
);
