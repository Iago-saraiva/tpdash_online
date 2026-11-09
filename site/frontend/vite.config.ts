import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// O build vai para site/static/app e é servido pelo próprio site (Flask).
// Os arquivos gerados vão para o GitHub: o Render e o painel local não precisam de Node.
export default defineConfig({
  plugins: [react()],
  base: "./",
  build: {
    outDir: "../static/app",
    emptyOutDir: true,
    manifest: true,
    rollupOptions: { input: "src/main.tsx" },
  },
});
