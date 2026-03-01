/** Shared utilities used across components. */

/** Format a score number as "0.850" */
export function formatScore(value: number | undefined): string {
    const n = Number(value);
    return Number.isFinite(n) ? n.toFixed(3) : "0.000";
}

/** Language code → human label */
export function langLabel(code: string): string {
    const labels: Record<string, string> = {
        es: "Español",
        en: "English",
        ca: "Català",
        fr: "Français",
        de: "Deutsch",
        pt: "Português",
        it: "Italiano",
    };
    return labels[code] || code || "";
}

/** ISO date → "10 ene 2025" / "ene 2025" / "2025" */
export function formatDateFacet(iso: string): string {
    if (!iso) return iso;
    const months = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"];
    const full = iso.match(/^(\d{4})-(\d{2})-(\d{2})$/);
    if (full) return `${parseInt(full[3])} ${months[parseInt(full[2]) - 1]} ${full[1]}`;
    const monthOnly = iso.match(/^(\d{4})-(\d{2})$/);
    if (monthOnly) return `${months[parseInt(monthOnly[2]) - 1]} ${monthOnly[1]}`;
    return iso;
}

/** Format file size: 23.4 KB, 12.1 MB */
export function formatSize(bytes: number): string {
    if (bytes < 1024) return bytes + " B";
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
    return (bytes / (1024 * 1024)).toFixed(1) + " MB";
}

/** Tailwind classes for document type badges */
export function typeColor(type: string): string {
    const m: Record<string, string> = {
        acta_reunion: "bg-purple-50 text-purple-700",
        email: "bg-yellow-50 text-yellow-700",
        memo: "bg-pink-50 text-pink-700",
        contrato: "bg-teal-50 text-teal-700",
        factura: "bg-orange-50 text-orange-700",
        informe: "bg-cyan-50 text-cyan-700",
        listado: "bg-lime-50 text-lime-700",
        documento: "bg-gray-100 text-gray-700",
        tabla: "bg-indigo-50 text-indigo-700",
        tickets: "bg-red-50 text-red-700",
        inventario: "bg-emerald-50 text-emerald-700",
        ventas: "bg-amber-50 text-amber-700",
    };
    return m[type] || "bg-gray-100 text-gray-700";
}

/** Convert **bold** markers to <mark> highlights */
export function formatHighlight(text: string): string {
    if (!text) return "";
    return text.replace(
        /\*\*(.+?)\*\*/g,
        '<mark class="bg-yellow-100 text-yellow-900 px-0.5 rounded">$1</mark>',
    );
}

/** Simple markdown→HTML for chat messages */
export function renderMarkdown(text: string): string {
    if (!text) return "";
    return text
        .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
        .replace(/\*(.+?)\*/g, "<em>$1</em>")
        .replace(/\[([^\]]+)\]/g, '<span class="text-blue-600 font-medium">[$1]</span>')
        .replace(/^### (.+)$/gm, '<h3 class="font-semibold text-base mt-2">$1</h3>')
        .replace(/^## (.+)$/gm, '<h2 class="font-semibold text-lg mt-2">$1</h2>')
        .replace(/^- (.+)$/gm, '<li class="ml-4 list-disc">$1</li>')
        .replace(/^(\d+)\. (.+)$/gm, '<li class="ml-4 list-decimal">$1. $2</li>')
        .replace(/\n/g, "<br>");
}

/** Allowed upload extensions */
export const ALLOWED_EXTENSIONS = [".txt", ".csv", ".pdf", ".docx", ".xlsx", ".xls"];
export const MAX_UPLOAD_MB = 50;
