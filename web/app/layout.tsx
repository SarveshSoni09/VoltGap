import type { Metadata } from "next";

import { FreshnessIndicator } from "../components/FreshnessIndicator";
import { ViewNav } from "../components/ViewNav";
import "./globals.css";

export const metadata: Metadata = {
  title: "VoltGap — EV charging siting decision support",
  description:
    "Given a budget and a set of policy priorities, where should the next EV charging infrastructure be built, and how confident should we be in that answer?",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <div className="shell">
          <header className="top">
            <div className="brand">
              Volt<span>Gap</span>
            </div>
            <ViewNav />
            <FreshnessIndicator />
          </header>
          <main>{children}</main>
        </div>
      </body>
    </html>
  );
}
