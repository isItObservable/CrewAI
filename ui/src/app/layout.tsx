import type { Metadata } from "next";
import "./globals.css";
import "@copilotkit/react-ui/styles.css";

export const metadata: Metadata = {
  title: "BMAD Crew — CrewAI + CopilotKit",
  description:
    "Drive the BMAD multi-agent software-delivery crew via natural language. " +
    "Powered by CrewAI and CopilotKit.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-slate-900 text-slate-100 antialiased">
        {children}
      </body>
    </html>
  );
}
