import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In development, /v1 and /health are proxied to the FastAPI server on :8000.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/v1": "http://localhost:8000",
      "/health": "http://localhost:8000",
    },
  },
});
