import { svelte } from "@sveltejs/vite-plugin-svelte";
import { defineConfig } from "vite";

const api = process.env.STEMLAB_DEV_API || "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [svelte()],
  server: {
    proxy: {
      "/api": api,
      "/health": api,
      "/docs": api,
      "/openapi.json": api,
      "/redoc": api,
    },
  },
});
