"use client";

export function Toast({ toast }: { toast: { msg: string; type: "ok" | "error" } | null }) {
    if (!toast) return null;
    return (
        <div className="fixed bottom-6 right-6 z-50 fade-in">
            <div
                className={`flex items-center gap-2 px-4 py-3 rounded-lg shadow-lg text-sm font-medium ${toast.type === "error" ? "bg-red-600 text-white" : "bg-ink-0 text-white"
                    }`}
            >
                {toast.msg}
            </div>
        </div>
    );
}
