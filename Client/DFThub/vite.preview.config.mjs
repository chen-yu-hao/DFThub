import { defineConfig } from "vite";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const apiTarget = process.env.DFTHUB_API_TARGET || "http://127.0.0.1:2002";

export default defineConfig({
  appType: "mpa",
  plugins: [
    {
      name: "dfthub-compatibility-redirect",
      configurePreviewServer(server) {
        server.middlewares.use((request, response, next) => {
          if (process.env.DFTHUB_ENABLE_HSTS === "1") {
            response.setHeader("Strict-Transport-Security", "max-age=31536000; includeSubDomains");
          }
          response.setHeader("X-Content-Type-Options", "nosniff");
          response.setHeader("Referrer-Policy", "strict-origin-when-cross-origin");
          response.setHeader("X-Frame-Options", "DENY");
          response.setHeader("Content-Security-Policy", "frame-ancestors 'none'");
          response.setHeader("Content-Security-Policy-Report-Only", "default-src 'self'; base-uri 'none'; object-src 'none'; frame-ancestors 'none'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; img-src 'self' data: blob:; connect-src 'self' https://dfthub.ecnu.space");
          next();
        });
        server.middlewares.use((request, response, next) => {
          const url = new URL(
            request.url || "/",
            "http://localhost",
          );
          const destination = url.pathname === "/dfthub" || url.pathname === "/dfthub/" ? "/"
            : ["/workspace", "/analyze", "/energy", "/guide"].includes(url.pathname) ? url.pathname + "/" : null;
          if (destination) {
            response.statusCode = 308;
            response.setHeader("Location", destination + url.search);
            response.end();
            return;
          }
          const acceptsHtml = String(request.headers.accept || "").includes("text/html");
          const pagePath = url.pathname.replace(/\/+$/, "") || "/";
          const knownPage = pagePath === "/" || pagePath === "/workspace" || pagePath === "/analyze" || pagePath === "/energy" || pagePath === "/guide" || pagePath === "/dfthub";
          if (request.method === "GET" && acceptsHtml && !knownPage && !/\.[^/]+$/.test(url.pathname) && !url.pathname.startsWith("/api_dft/") && !url.pathname.startsWith("/_astro/")) {
            try {
              response.statusCode = 404;
              response.setHeader("Content-Type", "text/html; charset=utf-8");
              response.end(readFileSync(resolve(process.cwd(), "dist-dfthub/404.html")));
              return;
            } catch { /* Let Vite handle missing build output. */ }
          }
          next();
        });
        server.middlewares.use(async (request, response, next) => {
          const pathname = new URL(request.url || "/", "http://localhost").pathname;
          const acceptsHtml = String(request.headers.accept || "").includes("text/html");
          const pagePath = pathname.replace(/\/+$/, "") || "/";
          const knownPage = pagePath === "/" || pagePath === "/workspace" || pagePath === "/analyze" || pagePath === "/energy" || pagePath === "/guide" || pagePath === "/dfthub";
          if (request.method !== "GET" || !acceptsHtml || knownPage || /\.[^/]+$/.test(pathname) || pathname.startsWith("/api_dft/") || pathname.startsWith("/_astro/")) return next();
          try {
            const body = readFileSync(resolve(process.cwd(), "dist-dfthub/404.html"));
            response.statusCode = 404;
            response.setHeader("Content-Type", "text/html; charset=utf-8");
            response.end(body);
          } catch {
            next();
          }
        });
      },
    },
  ],
  build: {
    outDir: "dist-dfthub",
  },
  preview: {
    host: "127.0.0.1",
    port: 8188,
    strictPort: true,
    allowedHosts: ["origin-dfthub.ecnu.space"],
    proxy: {
      "/api_dft": {
        target: apiTarget,
        changeOrigin: true,
      },
    },
  },
});
