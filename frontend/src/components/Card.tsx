import type { ReactNode } from "react";

export function Card({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <section className={`section-card ${className}`.trim()}>{children}</section>;
}
