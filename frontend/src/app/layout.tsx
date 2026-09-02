import "./globals.css";
import Sidebar from "@/components/Sidebar";

export const metadata = { title: "RazorSync v3 — Coordination Engine", description: "Cross-agent coordination for Razorpay Agent Studio — v3 with live Razorpay + statistical rigor" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet" />
      </head>
      <body className="min-h-screen bg-[#F6F8FA] text-slate-900 antialiased" style={{ fontFamily: "'Inter', system-ui, -apple-system, sans-serif" }}>
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
