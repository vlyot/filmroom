import { resolve } from "node:path"
import tailwindcss from "@tailwindcss/vite"
import react from "@vitejs/plugin-react"
import { defineConfig } from "vitest/config"

const repo = resolve(import.meta.dirname, "..")

// https://vite.dev/config/
export default defineConfig({
  // GitHub Pages serves the app under /<repo>/, set at build time.
  base: process.env.VITE_BASE ?? "/",
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": resolve(import.meta.dirname, "./src"),
      // Narrative templates and language rules are shared with the Python agent layer, not copied.
      "@agents": resolve(repo, "src/filmroom/agents"),
      "@contracts": resolve(repo, "contracts"),
    },
  },
  server: { fs: { allow: [repo] } },
  test: { include: ["src/**/*.test.ts"] },
})
