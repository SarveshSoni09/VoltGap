"use client";

import { useState } from "react";

/**
 * Detail the reader can open, not prose they must scroll past.
 *
 * The interface used to lead with evidence percentages, tier definitions and allocation
 * caveats. All of it is true and none of it belongs before a first-time reader knows what
 * they are looking at. This puts the depth one click away instead of removing it.
 */
export function Disclosure({
  question,
  children,
  tone = "plain",
}: {
  question: string;
  children: React.ReactNode;
  tone?: "plain" | "quiet";
}) {
  const [open, setOpen] = useState(false);
  return (
    <div className={`disclose ${tone}`}>
      <button
        type="button"
        className="disclose-q"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
      >
        <span className="chev" aria-hidden>{open ? "▾" : "▸"}</span>
        {question}
      </button>
      {open && <div className="disclose-a">{children}</div>}
    </div>
  );
}
