import type { Metadata, Viewport } from "next";
import { Archivo, Unbounded } from "next/font/google";
import Link from "next/link";
import { effectiveTier, getCurrentUser, isAdmin } from "@/lib/users";
import "./globals.css";

const display = Unbounded({ subsets: ["latin"], variable: "--font-display", display: "swap" });
const body = Archivo({ subsets: ["latin"], variable: "--font-body", display: "swap" });

export const metadata: Metadata = {
  title: { default: "Phillies Therapy Game Night", template: "%s · Game Night" },
  description: "The Phillies Therapy trivia game show. Watch live, play along, and take the contestant's chair.",
};

export const viewport: Viewport = { themeColor: "#632237", width: "device-width", initialScale: 1 };

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  const user = await getCurrentUser();
  return (
    <html lang="en" className={`${display.variable} ${body.variable}`}>
      <body>
        <header className="site-header">
          <div className="wrap">
            <Link href="/" className="wordmark">
              <b>Game Night</b>
              <span>Phillies Therapy</span>
            </Link>
            <nav className="nav" aria-label="Main">
              <Link href="/play">Play</Link>
              <Link href="/standings">Standings</Link>
              {user && effectiveTier(user) >= 3 && <Link href="/seat">Seat</Link>}
              {isAdmin(user) && <Link href="/admin">Host</Link>}
              {user ? (
                <Link href="/account">Account</Link>
              ) : (
                <a className="cta" href="/auth/patreon">
                  Sign in
                </a>
              )}
            </nav>
          </div>
        </header>
        <main className="wrap">{children}</main>
        <footer className="site-footer">
          <div className="wrap">Phillies Therapy Game Night. A fan production, not affiliated with the Philadelphia Phillies or MLB.</div>
        </footer>
      </body>
    </html>
  );
}
