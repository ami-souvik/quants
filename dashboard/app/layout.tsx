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
    <html lang="en" className="dark">
      <body className="bg-bg text-text antialiased">
        <div className="min-h-screen flex flex-col">
          <Nav />
          <main className="flex-1 container mx-auto px-4 py-6 max-w-7xl">
            {children}
          </main>
          <footer className="border-t border-border py-3 text-center text-xs text-subtle">
            Quants — Paper Trading Mode Only · Personal experiment · Not financial advice
          </footer>
        </div>
      </body>
    </html>
  );
}
