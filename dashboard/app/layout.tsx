import type { Metadata } from "next";
import "./globals.css";
import { Nav } from "@/components/Nav";

export const metadata: Metadata = {
  title: "Quants",
  description: "Multi-agent paper-trading dashboard for Indian equities (NSE)",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="bg-bg text-text antialiased">
        <div className="min-h-screen flex flex-col">
          <Nav />
          <main className="flex-1 w-full max-w-[1400px] mx-auto px-6 py-10">
            {children}
          </main>
          <footer className="border-t border-border py-4 px-6 mt-auto">
            <div className="max-w-[1400px] mx-auto flex items-center justify-between">
              <span className="text-[11px] text-muted">Quants © 2026</span>
              <span className="text-[11px] text-muted">
                Paper Trading · NSE · Personal Experiment · Not Financial Advice
              </span>
            </div>
          </footer>
        </div>
      </body>
    </html>
  );
}
