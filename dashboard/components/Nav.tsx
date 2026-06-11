"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import clsx from "clsx";

const LINKS = [
  { href: "/", label: "Dashboard" },
  { href: "/decisions", label: "Decisions" },
  { href: "/metrics", label: "Analytics" },
  { href: "/logs", label: "Logs" },
  { href: "/how-it-works", label: "How It Works" },
];

export function Nav() {
  const path = usePathname();
  return (
    <header className="border-b border-border bg-surface sticky top-0 z-40">
      <div className="container mx-auto px-4 max-w-7xl flex items-center justify-between h-14">
        <span className="font-semibold text-text flex items-center gap-2">
          <span className="text-accent text-lg">⬡</span>
          Quants
          <span className="ml-2 px-2 py-0.5 rounded text-xs bg-gold/20 text-gold font-mono">
            paper
          </span>
        </span>
        <nav className="flex gap-1">
          {LINKS.map(({ href, label }) => (
            <Link
              key={href}
              href={href}
              className={clsx(
                "px-3 py-1.5 rounded text-sm transition-colors",
                path === href
                  ? "bg-accent/20 text-accent"
                  : "text-subtle hover:text-text hover:bg-border/50"
              )}
            >
              {label}
            </Link>
          ))}
        </nav>
      </div>
    </header>
  );
}
