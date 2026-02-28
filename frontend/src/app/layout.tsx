import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "DocumentWho — Búsqueda Inteligente",
  description: "Busca, pregunta y explora tus documentos corporativos con IA",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="es">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link
          href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap"
          rel="stylesheet"
        />
      </head>
      <body className="bg-surface-1 text-ink-0 font-sans antialiased min-h-screen flex flex-col">
        {children}
      </body>
    </html>
  );
}
