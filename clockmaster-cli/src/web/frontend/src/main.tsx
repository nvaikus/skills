import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./index.css";
import { App } from "./app/App";
import { OverlayProvider } from "./ui/overlay";
import { ToastProvider } from "./ui/Toast";
import { TooltipLayer } from "./ui/Tooltip";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <OverlayProvider>
      <ToastProvider>
        <App />
        <TooltipLayer />
      </ToastProvider>
    </OverlayProvider>
  </StrictMode>,
);
