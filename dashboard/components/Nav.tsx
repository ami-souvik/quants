"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";

const NAV_LINKS = [
  { href: "/",           label: "Dashboard" },
  { href: "/decisions",  label: "Decisions" },
  { href: "/metrics",    label: "Analytics" },
  { href: "/logs",       label: "Logs" },
  { href: "/report",     label: "Report" },
  { href: "/how-it-works", label: "System" },
];

export function Nav() {
  const path = usePathname();
  return (
    <header className="border-b border-border sticky top-0 z-40 bg-bg">
      <div className="max-w-[1400px] mx-auto flex items-stretch h-14">
        {/* Wordmark */}
        <Link
          href="/"
          className="flex items-center px-6 border-r border-border text-text font-semibold text-[15px] tracking-tight shrink-0 select-none"
        >
          Quants<sup className="text-[9px] text-muted ml-0.5 font-normal">TM</sup>
        </Link>

        {/* Tab links */}
        <nav className="flex items-stretch">
          {NAV_LINKS.map(({ href, label }) => {
            const active = path === href;
            return (
              <Link
                key={href}
                href={href}
                className={`
                  flex flex-col justify-center px-6 border-r border-border text-[13px] font-medium
                  transition-colors relative
                  ${active
                    ? "bg-accent text-accent-fg"
                    : "text-muted hover:text-text hover:bg-surface"
                  }
                `}
              >
                {label}
              </Link>
            );
          })}
        </nav>

        {/* Right spacer + badge */}
        <div className="ml-auto flex items-center px-6 border-l border-border">
          <span className="text-[11px] text-accent font-mono tracking-widest border border-accent/40 px-2 py-0.5">
            PAPER
          </span>
        </div>
      </div>
    </header>
  );
}
