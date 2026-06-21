import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "System Status — SolidAI SRE",
  description: "Real-time health status of SolidAI SRE and Solid Solutions infrastructure",
};

/**
 * Public layout — no sidebar, no auth gate, no visitor session.
 * Used for the status page which must be accessible without tokens.
 */
export default function PublicLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return <>{children}</>;
}
