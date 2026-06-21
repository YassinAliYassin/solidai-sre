import type { Metadata } from "next";
import "./globals.css";
import { Sidebar } from "@/components/Sidebar";
import { SignInGate } from "@/components/SignInGate";
import { ThemeProvider } from "@/components/ThemeProvider";
import { VisitorSessionProvider } from "@/components/VisitorSessionProvider";
import { VisitorWarningBanner } from "@/components/VisitorWarningBanner";

export const metadata: Metadata = {
  title: "SolidAI SRE",
  description: "AI-Powered SRE Platform for Solid Solutions & SolidAI",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="h-full" suppressHydrationWarning>
      <head>
        {/* CRITICAL: This script MUST run before any rendering to prevent flash */}
        <script
          dangerouslySetInnerHTML={{
            __html: `
              (function() {
                try {
                  const theme = localStorage.getItem('theme') || 'light';
                  const root = document.documentElement;
                  if (theme === 'dark') {
                    root.classList.add('dark');
                    root.style.colorScheme = 'dark';
                  } else {
                    root.classList.remove('dark');
                    root.style.colorScheme = 'light';
                  }
                } catch (e) {}
              })();
            `,
          }}
        />
      </head>
      <body
        className={`antialiased h-full bg-stone-50 dark:bg-stone-900`}
      >
        <ThemeProvider>
          <SignInGate>
            <VisitorSessionProvider>
              <div className="min-h-screen">
                <Sidebar />
                <main className="lg:pl-64 min-h-screen transition-all duration-200">{children}</main>
              </div>
              <VisitorWarningBanner />
            </VisitorSessionProvider>
          </SignInGate>
        </ThemeProvider>
      </body>
    </html>
  );
}
