import type { Metadata } from 'next'
import { Inter } from 'next/font/google'
import './globals.css'
import Link from 'next/link'
import { cn } from '@/lib/utils'

const inter = Inter({ subsets: ['latin'], variable: '--font-sans' })

export const metadata: Metadata = {
  title: 'Job Scraper Dashboard',
  description: 'Personal job tracking dashboard — Dewangga Dewata Indera',
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="en" className={cn(inter.variable, 'dark font-sans antialiased')}>
      <body className="min-h-screen bg-background text-foreground">
        <nav className="sticky top-0 z-50 border-b border-border/80 bg-background/80 backdrop-blur-md supports-[backdrop-filter]:bg-background/60">
          <div className="mx-auto flex h-14 max-w-7xl items-center justify-between px-4 sm:px-6 lg:px-8">
            <Link
              href="/"
              className="flex items-center gap-2 text-lg font-semibold tracking-tight text-foreground transition-colors hover:text-primary"
            >
              <span className="text-xl" aria-hidden>
                ◉
              </span>
              <span className="hidden sm:inline">Job Scraper</span>
            </Link>
            <div className="flex items-center gap-0.5">
              <NavLink href="/" label="Jobs" />
              <NavLink href="/tracker" label="Tracker" />
            </div>
          </div>
        </nav>

        <main className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">{children}</main>

        <footer className="mt-16 border-t border-border">
          <div className="mx-auto max-w-7xl px-4 py-6 text-center text-xs text-muted-foreground sm:px-6 lg:px-8">
            Job Scraper · Runs on GitHub Actions every 4 hours · Built for Dewangga Dewata Indera
          </div>
        </footer>
      </body>
    </html>
  )
}

function NavLink({ href, label }: { href: string; label: string }) {
  return (
    <Link
      href={href}
      className="rounded-md px-3 py-2 text-sm font-medium text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground"
    >
      {label}
    </Link>
  )
}
