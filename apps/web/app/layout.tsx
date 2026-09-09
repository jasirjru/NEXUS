import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "NEXUS — Autonomous Intelligence & Decision Engine",
  description:
    "Ethereum intelligence platform: anomaly detection, calibrated risk, AI investigation.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>
        <div className="shell">
          <aside className="sidebar">
            <div className="brand">
              <span className="brand-mark">N</span>
              <span className="brand-name">NEXUS</span>
            </div>
            <nav>
              {[
                ["/", "Overview", "◉"],
                ["/network", "Network Intelligence", "⬡"],
                ["/anomalies", "Anomaly Detection", "△"],
                ["/risk", "Risk Monitoring", "◈"],
                ["/entities", "Entity Investigation", "◇"],
                ["/graph", "Graph Explorer", "⁂"],
                ["/temporal", "Temporal Behavior", "∿"],
                ["/investigator", "AI Investigator", "✦"],
                ["/alerts", "Alerts", "●"],
                ["/automations", "Automations", "⚙"],
                ["/models", "Model Performance", "∖"],
                ["/system", "System / MLOps", "▦"],
              ].map(([href, label, icon]) => (
                <a key={href} href={href} className="nav-item">
                  <span className="nav-icon">{icon}</span>
                  {label}
                </a>
              ))}
            </nav>
            <div className="sidebar-footer">
              <span className="pulse" /> intelligence loop active
            </div>
          </aside>
          <main className="main">{children}</main>
        </div>
      </body>
    </html>
  );
}
