import type { Metadata } from "next";
import type { ReactNode } from "react";
import MuseLanguageProvider from "../components/muse-language-provider";
import "./globals.css";

export const metadata: Metadata = {
  title: "FORMA",
  description: "Build with measured materials. Adapt when the build changes.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    // Dark-mode extensions can add attributes to the document before hydration.
    <html lang="en" suppressHydrationWarning>
      <body>
        <MuseLanguageProvider>{children}</MuseLanguageProvider>
      </body>
    </html>
  );
}
