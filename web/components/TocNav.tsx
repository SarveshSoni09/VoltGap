"use client";

import { useEffect, useState } from "react";

/**
 * Sticky contents for a long technical page, with the current section highlighted.
 *
 * Uses an IntersectionObserver rather than scroll maths: it reports which headings are on
 * screen without running a handler on every scroll frame, which matters on a page that also
 * has to stay within a frame-rate budget elsewhere in the product.
 *
 * Degrades to a plain list of links if the observer is unavailable — the navigation still
 * works, it simply stops tracking position.
 */
export interface TocSection {
  readonly id: string;
  readonly label: string;
}

export function TocNav({ sections }: { readonly sections: readonly TocSection[] }) {
  const [active, setActive] = useState<string | null>(null);

  useEffect(() => {
    if (typeof IntersectionObserver === "undefined") return;
    const seen = new Map<string, boolean>();
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          seen.set(entry.target.id, entry.isIntersecting);
        }
        // The topmost heading currently on screen wins, so the highlight matches what the
        // reader is looking at rather than whatever fired most recently.
        const current = sections.find((s) => seen.get(s.id) === true);
        if (current !== undefined) setActive(current.id);
      },
      // Bias the band toward the top of the viewport: a heading is "current" once it
      // reaches the upper third, not when it first peeks in at the bottom.
      { rootMargin: "-80px 0px -66% 0px", threshold: 0 },
    );
    for (const section of sections) {
      const el = document.getElementById(section.id);
      if (el !== null) observer.observe(el);
    }
    return () => observer.disconnect();
  }, [sections]);

  return (
    <nav className="toc" aria-label="Contents">
      <div className="toc-title">Contents</div>
      <ol>
        {sections.map((section) => (
          <li key={section.id}>
            <a
              href={`#${section.id}`}
              className={active === section.id ? "current" : undefined}
              aria-current={active === section.id ? "true" : undefined}
            >
              {section.label}
            </a>
          </li>
        ))}
      </ol>
    </nav>
  );
}
