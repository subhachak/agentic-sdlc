export const metadata = {
  title: "Claims Lite",
  description: "Sample app for the agentic QA pipeline demo",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
