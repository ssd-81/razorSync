import "./globals.css";
import { Inter } from "next/font/google";
import Sidebar from "@/components/Sidebar";

const inter = Inter({ subsets: ["latin"], display: "swap" });

export const metadata = { title: "RazorSync — Coordination Engine", description: "Coordination layer for customer touchpoints: policy scoring, windowed rules, and human review." };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className={`min-h-screen bg-[#F6F8FA] text-slate-900 antialiased ${inter.className}`}>
        <div className="flex min-h-screen">
          <Sidebar />
          <main className="flex-1 min-w-0 bg-[#F6F8FA]">
            <div className="max-w-[1160px] mx-auto px-6 py-6 lg:px-8">{children}</div>
          </main>
        </div>
      </body>
    </html>
  );
}
