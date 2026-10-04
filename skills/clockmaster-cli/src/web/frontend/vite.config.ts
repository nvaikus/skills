import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
// @ts-ignore dev-only plain-JS mock, never part of the build
import { mockApi } from "./dev/mock.js";

// not type-checked by tsc (src/ only); CLOCKMASTER_API points the dev proxy elsewhere
declare const process: { env: Record<string, string | undefined> };
const API = process.env.CLOCKMASTER_API ?? "http://127.0.0.1:7788";

// Build output is committed at src/web/dist/ — server.py serves the SPA from there.
// `npm run mock` (vite --mode mock) answers /api from an in-memory fixture instead
// of proxying to a running `clockmaster ui` (7788, or $CLOCKMASTER_API).
export default defineConfig(({ mode }) => ({
  plugins: [react(), tailwindcss(), ...(mode === "mock" ? [mockApi()] : [])],
  base: "./",
  build: { outDir: "../dist", emptyOutDir: true, chunkSizeWarningLimit: 800 },
  server: {
    port: 5180,
    host: "127.0.0.1",
    proxy: mode === "mock" ? undefined : { "/api": API },
  },
}));
