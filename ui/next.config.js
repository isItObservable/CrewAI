/** @type {import('next').NextConfig} */
const nextConfig = {
  // Required for the multi-stage Dockerfile (copies only the minimal runtime bundle).
  output: "standalone",
  // Proxying /api/crew/* is handled by src/app/api/crew/[...path]/route.ts
  // which reads BMAD_CREW_URL at request time (not baked at build time).
};

module.exports = nextConfig;
