import type { Metadata } from "next";
import { Fraunces, Inter } from "next/font/google";

import AppShell from "@/components/AppShell";

import "./globals.css";

const fraunces = Fraunces({
  subsets: ["latin"],
  weight: "600",
  variable: "--font-fraunces",
});

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
});

export const metadata: Metadata = {
  title: "The Ledger",
  description: "Google Analytics 4 reporting dashboard",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className={`${fraunces.variable} ${inter.variable}`}>
        <AppShell>{children}</AppShell>
      </body>
    </html>
  );
}
