import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// /v1 and /health are proxied to the FastAPI server on :8000, both in development (`npm run dev`)
// and when previewing a production build (`npm run preview`). In Docker, nginx does the same job.
const apiProxy = {
  "/v1": "http://localhost:8000",
  "/health": "http://localhost:8000",
};

export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy: apiProxy },
  preview: { port: 4173, proxy: apiProxy },
});
