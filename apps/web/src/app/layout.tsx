import type { Metadata } from "next";
import type { ReactNode } from "react";
import MuseLanguageProvider from "../components/muse-language-provider";
import "./globals.css";

const description =
  "Turn measured reused materials into a tabletop fixture with a checked assembly manual, and repair the build when it disagrees with the plan.";

export const metadata: Metadata = {
  title: "FORMA",
  description,
  openGraph: { title: "FORMA", description, type: "website" },
};

// Answer engines and agents read this instead of rendering the client app.
const jsonLd = {
  "@context": "https://schema.org",
  "@type": "SoftwareApplication",
  name: "FORMA",
  applicationCategory: "DesignApplication",
  operatingSystem: "Web",
  description:
    "FORMA turns photographed, measured reused materials into a small tabletop fixture and a step-by-step assembly manual. Meta's Muse model proposes designs and diagnoses failure photos; a deterministic Assembly Compiler validates stock, geometry and joints, and repairs keep usable completed work.",
  codeRepository: "https://github.com/olartgabo/forma",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    // Dark-mode extensions can add attributes to the document before hydration.
    <html lang="en" suppressHydrationWarning>
      <head>
        <link rel="alternate" type="text/plain" href="/llms.txt" />
      </head>
      <body>
        <script
          type="application/ld+json"
          dangerouslySetInnerHTML={{
            __html: JSON.stringify(jsonLd).replace(/</g, "\\u003c"),
          }}
        />
        <MuseLanguageProvider>{children}</MuseLanguageProvider>
      </body>
    </html>
  );
}
