import { defineConfig } from "astro/config";
import react from "@astrojs/react";

const apiTarget = process.env.DFTHUB_API_TARGET || "http://127.0.0.1:2002";

export default defineConfig({
  base: "/",
  output: "static",
  outDir: "./dist-dfthub",
  publicDir: "./public",
  redirects: {
    "/dfthub": "/",
  },
  integrations: [react()],
  server: {
    host: "127.0.0.1",
    port: 8288,
  },
  vite: {
    server: {
      strictPort: true,
      proxy: {
        "/api_dft": {
          target: apiTarget,
          changeOrigin: true,
        },
      },
    },
  },
});
