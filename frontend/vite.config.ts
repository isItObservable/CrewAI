import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev proxy: the app calls same-origin /copilotkit and Vite forwards it to the
// FastAPI BFF (bmad_crew/copilotkit_bff.py). No CORS needed in the dev flow.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/copilotkit": {
        target: "http://localhost:8100",
        changeOrigin: true,
      },
    },
  },
});
