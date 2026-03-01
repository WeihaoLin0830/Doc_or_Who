"use client";

import { useState, useRef } from "react";
import * as api from "@/lib/api";
import type { UploadResult } from "@/lib/types";
import { formatSize, ALLOWED_EXTENSIONS, MAX_UPLOAD_MB, typeColor } from "@/lib/utils";

interface Props {
    ingesting: boolean;
    onClose: () => void;
    onComplete: () => void;
}

export function UploadModal({ ingesting, onClose, onComplete }: Props) {
    const [selectedFile, setSelectedFile] = useState<File | null>(null);
    const [uploading, setUploading] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [result, setResult] = useState<UploadResult | null>(null);
    const [dragOver, setDragOver] = useState(false);
    const inputRef = useRef<HTMLInputElement>(null);

    function selectFile(file: File) {
        setError(null);
        if (file.size > MAX_UPLOAD_MB * 1024 * 1024) {
            setError(`Archivo demasiado grande (${formatSize(file.size)}). Máximo ${MAX_UPLOAD_MB} MB.`);
            return;
        }
        const ext = "." + file.name.split(".").pop()?.toLowerCase();
        if (!ALLOWED_EXTENSIONS.includes(ext)) {
            setError(`Formato '${ext}' no soportado. Usa: ${ALLOWED_EXTENSIONS.join(", ")}.`);
            return;
        }
        setSelectedFile(file);
    }

    async function doUpload() {
        if (!selectedFile) return;
        setUploading(true);
        setError(null);
        try {
            const data = await api.uploadFile(selectedFile);
            setResult(data);
            onComplete();
        } catch (e: unknown) {
            setError(e instanceof Error ? e.message : "Error desconocido al procesar el archivo.");
        } finally {
            setUploading(false);
        }
    }

    function reset() {
        setSelectedFile(null);
        setUploading(false);
        setError(null);
        setResult(null);
    }

    return (
        <div
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm"
            onClick={(e) => { if (e.target === e.currentTarget && !uploading) { onClose(); reset(); } }}
        >
            <div className="bg-white rounded-xl shadow-xl w-full max-w-md mx-4 p-6 fade-in">
                {/* Header */}
                <div className="flex items-center justify-between mb-5">
                    <h3 className="text-base font-semibold text-ink-0">Subir documento</h3>
                    <button
                        onClick={() => { onClose(); reset(); }}
                        disabled={uploading}
                        className="text-ink-3 hover:text-ink-0 disabled:opacity-30 transition-opacity"
                    >
                        <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                        </svg>
                    </button>
                </div>

                {/* Idle / file selected */}
                {!uploading && !result && (
                    <div>
                        {ingesting && (
                            <div className="mb-3 p-3 bg-amber-50 border border-amber-200 rounded-lg text-sm text-amber-700">
                                Re-indexación en curso. No se pueden subir archivos ahora.
                            </div>
                        )}

                        <div
                            className={`border-2 border-dashed rounded-xl p-6 text-center transition-colors ${dragOver
                                    ? "border-brand-400 bg-brand-50"
                                    : selectedFile
                                        ? "border-brand-300 bg-brand-50/40"
                                        : "border-surface-3 hover:border-surface-2"
                                }`}
                            onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
                            onDragLeave={() => setDragOver(false)}
                            onDrop={(e) => { e.preventDefault(); setDragOver(false); const f = e.dataTransfer?.files?.[0]; if (f) selectFile(f); }}
                        >
                            {!selectedFile ? (
                                <div>
                                    <svg className="w-10 h-10 mx-auto text-ink-3 mb-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
                                            d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
                                    </svg>
                                    <p className="text-sm text-ink-1 mb-1">Arrastra un archivo o</p>
                                    <button
                                        onClick={() => inputRef.current?.click()}
                                        className="text-sm font-medium text-brand-600 hover:text-brand-700"
                                    >
                                        selecciona desde tu equipo
                                    </button>
                                    <input
                                        ref={inputRef}
                                        type="file"
                                        className="hidden"
                                        accept={ALLOWED_EXTENSIONS.join(",")}
                                        onChange={(e) => { const f = e.target.files?.[0]; if (f) selectFile(f); }}
                                    />
                                    <p className="text-xs text-ink-3 mt-2">
                                        {ALLOWED_EXTENSIONS.join(", ")} · máx {MAX_UPLOAD_MB} MB
                                    </p>
                                </div>
                            ) : (
                                <div>
                                    <svg className="w-8 h-8 mx-auto text-brand-500 mb-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
                                            d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                                    </svg>
                                    <p className="text-sm font-medium text-ink-0 mb-0.5">{selectedFile.name}</p>
                                    <p className="text-xs text-ink-3">{formatSize(selectedFile.size)}</p>
                                    <button
                                        onClick={() => { setSelectedFile(null); setError(null); }}
                                        className="text-xs text-ink-3 hover:text-red-500 mt-2 transition-colors"
                                    >
                                        Cambiar archivo
                                    </button>
                                </div>
                            )}
                        </div>

                        {/* Error */}
                        {error && (
                            <div className="mt-3 flex items-start gap-2 p-3 bg-red-50 border border-red-100 rounded-lg">
                                <svg className="w-4 h-4 text-red-500 mt-0.5 shrink-0" fill="currentColor" viewBox="0 0 20 20">
                                    <path fillRule="evenodd"
                                        d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z"
                                        clipRule="evenodd" />
                                </svg>
                                <p className="text-sm text-red-700">{error}</p>
                            </div>
                        )}

                        {/* Actions */}
                        <div className="mt-4 flex justify-end gap-2">
                            <button
                                onClick={() => { onClose(); reset(); }}
                                className="px-4 py-2 text-sm text-ink-1 hover:text-ink-0 rounded-lg transition-colors"
                            >
                                Cancelar
                            </button>
                            <button
                                onClick={doUpload}
                                disabled={!selectedFile || ingesting}
                                className="inline-flex items-center gap-1.5 px-4 py-2 text-sm font-medium text-white bg-brand-600 hover:bg-brand-700 rounded-lg transition-colors disabled:opacity-40"
                            >
                                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                                        d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12" />
                                </svg>
                                Subir y procesar
                            </button>
                        </div>
                    </div>
                )}

                {/* Uploading */}
                {uploading && (
                    <div className="py-10 text-center">
                        <svg className="w-12 h-12 mx-auto text-brand-600 animate-spin mb-4" fill="none" viewBox="0 0 24 24">
                            <circle className="opacity-20" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                            <path className="opacity-80" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                        </svg>
                        <p className="text-sm font-medium text-ink-0 mb-1">Procesando documento...</p>
                        <p className="text-xs text-ink-3">{selectedFile?.name || ""}</p>
                    </div>
                )}

                {/* Success */}
                {result && !uploading && (
                    <div className="py-6 text-center">
                        <div className="w-14 h-14 mx-auto bg-green-100 rounded-full flex items-center justify-center mb-4">
                            <svg className="w-7 h-7 text-green-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M5 13l4 4L19 7" />
                            </svg>
                        </div>
                        <p className="text-sm font-semibold text-ink-0 mb-1">{result.filename}</p>
                        <div className="flex items-center justify-center gap-2 mt-2">
                            <span className={`inline-flex px-2 py-0.5 rounded text-xs font-medium ${typeColor(result.doc_type)}`}>
                                {result.doc_type}
                            </span>
                            <span className="text-xs text-ink-3">{result.language}</span>
                            <span className="text-xs text-ink-3">·</span>
                            <span className="text-xs text-ink-3">{result.chunks_indexed} chunks</span>
                        </div>
                        <div className="mt-5 flex justify-center gap-2">
                            <button
                                onClick={reset}
                                className="px-4 py-2 text-sm font-medium text-brand-600 hover:text-brand-700"
                            >
                                Subir otro
                            </button>
                            <button
                                onClick={() => { onClose(); reset(); }}
                                className="px-4 py-2 text-sm font-medium text-white bg-brand-600 hover:bg-brand-700 rounded-lg"
                            >
                                Cerrar
                            </button>
                        </div>
                    </div>
                )}
            </div>
        </div>
    );
}
