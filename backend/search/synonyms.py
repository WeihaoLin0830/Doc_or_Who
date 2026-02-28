"""
synonyms.py — Expansión de sinónimos basada en vectores fastText españoles.

Descarga los vectores de palabras fastText en español (Common Crawl, Facebook AI)
y usa similitud coseno para encontrar sinónimos y términos relacionados reales.

Fuente: https://fasttext.cc/docs/en/crawl-vectors.html
Modelo: cc.es.300.vec.gz — entrenado en Common Crawl + Wikipedia español
Licencia: CC BY-SA 3.0

Flujo:
  1. Primera ejecución (~2-3 min): descarga streaming las top-200k palabras del
     fichero de vectores y guarda caché en data/fasttext_es.npz (~35 MB).
  2. Ejecuciones posteriores: carga desde caché local en <1s.
  3. expand(word) → cosine similarity → top-K vecinos (filtrando variantes
     morfológicas triviales como plurales, mayúsculas y acento exacto).

Por qué fastText y no co-occurrence/Jaccard:
  - Trained on >600B tokens de texto web español real.
  - Captura relaciones semánticas reales: reunión→[asamblea, sesión, junta],
    contrato→[convenio, arrendamiento], factura→[recibo, nómina, boleta].
  - No requiere un corpus propio grande ni hardcoding de ningún diccionario.
  - La caché local evita re-descargar en cada arranque.
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Optional

import numpy as np


# ─── Configuración ───────────────────────────────────────────────
FASTTEXT_URL = (
    "https://dl.fbaipublicfiles.com/fasttext/vectors-crawl/cc.es.300.vec.gz"
)
CACHE_FILE = Path(__file__).parent.parent.parent / "data" / "fasttext_es.npz"
TOP_N_WORDS = 200_000      # palabras más frecuentes a descargar (cubre vocab técnico)
_STOPWORDS: frozenset[str] = frozenset({
    # Prepositions / conjunctions that leak into expansions
    "segun", "aunque", "porque", "cuando", "donde", "durante", "mediante",
    "entre", "sobre", "desde", "hasta", "hacia", "contra", "dentro",
    "fuera", "antes", "despues", "dicho", "dicha", "dichos", "dichas",
    "mismo", "misma", "mismos", "mismas", "todo", "toda", "todos", "todas",
    "este", "esta", "estos", "estas", "aquel", "aquella",
})


def _norm(text: str) -> str:
    """Elimina acentos y minusculiza para comparaciones morfológicas."""
    nfd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfd if not unicodedata.combining(c)).lower()


def _is_morph_variant(query_norm: str, candidate: str) -> bool:
    """
    Devuelve True si el candidato es una variante morfológica trivial.
    Descarta: plurales (-s/-es), formas verbales, prefijados (de-/des-/pre-),
    mayúsculas/minúsculas exactas.
    """
    cn = _norm(candidate)
    if cn == query_norm:
        return True
    # El término búscado está contenido en el candidato (ej. acuerdo → deacuerdo)
    if query_norm in cn:
        return True
    # Mismo root (primeros N chars), solo difiere el sufijo
    root_len = max(4, len(query_norm) - 2)
    if len(cn) >= root_len and cn[:root_len] == query_norm[:root_len]:
        return True
    return False


# ─── Descarga + caché ────────────────────────────────────────────

def _download_vectors(url: str, top_n: int, cache_path: Path) -> tuple[list[str], np.ndarray]:
    """
    Descarga en streaming las primeras top_n palabras del fichero fastText
    y las guarda como caché numpy comprimida.

    El fichero está en formato word2vec texto:
        primera línea: "<vocab_size> <dim>"
        resto: "<word> <f1> <f2> ... <f300>"
    Las palabras están ordenadas por frecuencia descendente, por lo que
    sólo descargamos lo necesario (streaming, no descargamos el 5GB completo).
    """
    import urllib.request
    import gzip

    print(f"⬇️  Descargando vectores fastText español (top-{top_n:,} palabras)…")
    print(f"    Fuente: {url}")
    print(f"    Esto ocurre UNA SOLA VEZ — caché en {cache_path}")

    words: list[str] = []
    vectors: list[list[float]] = []

    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=300) as resp:
        with gzip.open(resp, "rt", encoding="utf-8", errors="ignore") as f:
            _header = f.readline()              # "2000000 300"
            for i, line in enumerate(f):
                if i >= top_n:
                    break
                parts = line.rstrip().split(" ")
                if len(parts) != _DIMS + 1:
                    continue
                word = parts[0]
                # Filtrar tokens que no son texto útil
                if not re.match(r"^[a-zA-ZáéíóúüñÁÉÍÓÚÜÑ]+$", word):
                    continue
                vf = [float(x) for x in parts[1:]]
                words.append(word)
                vectors.append(vf)
                if (i + 1) % 50_000 == 0:
                    print(f"    {i + 1:,} / {top_n:,} palabras procesadas…")

    mat = np.array(vectors, dtype=np.float32)
    # L2-normalizar para que el producto escalar = cosine similarity
    norms = np.linalg.norm(mat, axis=1, keepdims=True)
    mat = mat / np.maximum(norms, 1e-9)

    # Guardar caché (float16 para ahorrar espacio: ~35 MB para 200k palabras)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        cache_path,
        words=np.array(words, dtype=object),
        vectors=mat.astype(np.float16),
    )
    print(f"✅ Vectores fastText guardados en {cache_path} ({cache_path.stat().st_size // 1024 // 1024} MB)")
    return words, mat


def _load_cached(cache_path: Path) -> tuple[list[str], np.ndarray]:
    data = np.load(cache_path, allow_pickle=True)
    words = list(data["words"])
    mat = data["vectors"].astype(np.float32)   # float16 → float32 para operaciones
    return words, mat


# ─── Expansor principal ──────────────────────────────────────────

class FastTextExpander:
    """
    Expande términos de búsqueda usando vecinos más cercanos en el espacio
    vectorial fastText. Da sinónimos y términos semánticamente relacionados
    reales, aprendidos de cientos de millones de tokens de texto español.
    """

    def __init__(self) -> None:
        self._words: list[str] = []
        self._mat: Optional[np.ndarray] = None
        self._w2i: dict[str, int] = {}
        self._cache: dict[str, list[str]] = {}
        self._ready = False

    def initialize(
        self,
        cache_file: Path = CACHE_FILE,
        url: str = FASTTEXT_URL,
        top_n: int = TOP_N_WORDS,
    ) -> None:
        """
        Carga el modelo desde caché o lo descarga si no existe.
        Idempotente: si ya está inicializado no hace nada.
        """
        if self._ready:
            return

        if cache_file.exists():
            print(f"📂 Cargando vectores fastText desde caché ({cache_file.name})…")
            words, mat = _load_cached(cache_file)
        else:
            words, mat = _download_vectors(url, top_n, cache_file)

        self._words = words
        self._mat = mat
        self._w2i = {w: i for i, w in enumerate(words)}
        self._ready = True
        print(f"✅ Expansor fastText listo — {len(words):,} palabras españolas.")

    @property
    def ready(self) -> bool:
        return self._ready

    def expand(
        self,
        term: str,
        top_k: int = 6,
        min_sim: float = 0.45,
    ) -> list[str]:
        """
        Devuelve hasta top_k sinónimos/términos semánticamente similares.

        Prueba primero con el término exacto, luego sin acentos si no existe.

        Args:
            term:    Palabra a expandir (acentuada o no).
            top_k:   Máximo de resultados.
            min_sim: Similitud coseno mínima (0-1). 0.50 es conservador para
                     español: captura sinónimos sin ruido excesivo.
        """
        if not self._ready or self._mat is None:
            return []

        cache_key = _norm(term)
        if cache_key in self._cache:
            return self._cache[cache_key]

        # Intentar lookup con el término original, luego normalizado
        idx_key = self._w2i.get(term) or self._w2i.get(_norm(term))
        if idx_key is None:
            # Último intento: capitalizado (ej. "Reunión")
            cap = term.capitalize()
            idx_key = self._w2i.get(cap)
        if idx_key is None:
            self._cache[cache_key] = []
            return []

        q_vec = self._mat[idx_key]                # shape (300,)
        sims = self._mat @ q_vec                   # shape (V,)
        sorted_idx = sims.argsort()[::-1]

        results: list[str] = []
        for i in sorted_idx:
            if float(sims[i]) < min_sim:
                break
            candidate = self._words[i]
            # Excluir el propio término y variantes morfológicas triviales
            if _is_morph_variant(cache_key, candidate):
                continue
            # Solo palabras alfabéticas en español, sin stopwords
            if not re.match(r"^[a-záéíóúüñA-ZÁÉÍÓÚÜÑ]{3,20}$", candidate):
                continue
            if _norm(candidate) in _STOPWORDS:
                continue
            results.append(candidate)
            if len(results) >= top_k:
                break

        self._cache[cache_key] = results
        return results

    def expand_query(self, query: str, top_k: int = 4) -> str:
        """
        Expande cada palabra de la query con sus sinónimos/términos cercanos.
        Solo se llama en el fallback Or-BM25 (cuando búsqueda And = 0 hits).
        Retorna query original + términos extras como string.
        """
        if not self._ready:
            return query

        # Extraer tokens alfabéticos de la query
        tokens = re.findall(r"[a-záéíóúüñA-ZÁÉÍÓÚÜÑ]{4,}", query)
        if not tokens:
            return query

        seen = set(_norm(t) for t in tokens)
        extras: list[str] = []

        for token in tokens:
            for syn in self.expand(token, top_k=top_k, min_sim=0.45):
                syn_n = _norm(syn)
                if syn_n not in seen:
                    extras.append(syn)
                    seen.add(syn_n)

        return (query + " " + " ".join(extras)).strip() if extras else query

    def debug_term(self, term: str, top_k: int = 15) -> list[dict]:
        """Devuelve los K vecinos más cercanos con puntuación (para debugging)."""
        if not self._ready or self._mat is None:
            return [{"error": "expansor no inicializado"}]

        idx_key = self._w2i.get(term) or self._w2i.get(_norm(term))
        if idx_key is None:
            return [{"error": f"'{term}' no encontrado en vocabulario fastText"}]

        q_vec = self._mat[idx_key]
        sims = self._mat @ q_vec
        sorted_idx = sims.argsort()[::-1][:top_k + 5]

        return [
            {"word": self._words[i], "cosine_sim": round(float(sims[i]), 4)}
            for i in sorted_idx
            if self._words[i] != term
        ][:top_k]


# ─── Instancia global ────────────────────────────────────────────

_expander = FastTextExpander()


def get_expander() -> FastTextExpander:
    """Devuelve la instancia global del expansor."""
    return _expander


def initialize_synonyms() -> None:
    """
    Inicializa el expansor fastText.
    Carga desde caché local si existe, o descarga en streaming (~2-3 min).
    Es idempotente: llamadas repetidas no hacen nada.

    Se llama desde api.py en el evento @startup.
    """
    _expander.initialize()
