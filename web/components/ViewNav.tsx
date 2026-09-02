"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

/**
 * The four Core views. Methodology and Validation is a first-class view, not a footer
 * link (§11.1) - the caveats are part of the product, not small print.
 */
const VIEWS = [
  { href: "/", label: "EV demand" },
  { href: "/access/", label: "Charging gaps" },
  { href: "/studio/", label: "Plan locations" },
  { href: "/methodology/", label: "How it works" },
] as const;

export function ViewNav() {
  const pathname = usePathname();
  const normalised = pathname.endsWith("/") ? pathname : `${pathname}/`;
  return (
    <nav className="views">
      {VIEWS.map((view) => (
        <Link
          key={view.href}
          href={view.href}
          aria-current={normalised === view.href ? "page" : undefined}
        >
          {view.label}
        </Link>
      ))}
    </nav>
  );
}
