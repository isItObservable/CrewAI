/** @type {import('next').NextConfig} */
const nextConfig = {
  // Required for the multi-stage Dockerfile (copies only the minimal runtime bundle).
  output: "standalone",
  // Allow the Next.js server to call the bmad-crew FastAPI backend.
  async rewrites() {
    const backendUrl = process.env.BMAD_CREW_URL || "http://localhost:8000";
    return [
      {
        source: "/api/crew/:path*",
        destination: `${backendUrl}/:path*`,
      },
    ];
  },
};

module.exports = nextConfig;
