import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// O build vai para admin/static/app e é servido pelo próprio ADMIN (Flask).
// Os arquivos gerados vão para o GitHub: o Render e o seu computador não precisam de Node.
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
