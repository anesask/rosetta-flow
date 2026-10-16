import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The bundle is committed under src/rosetta_flow/app/static so the Docker image needs no Node.
export default defineConfig({
  plugins: [react()],
  build: { outDir: "../src/rosetta_flow/app/static", emptyOutDir: true },
  server: { proxy: { "/api": "http://127.0.0.1:8000" } },
});
