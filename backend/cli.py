from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from backend.db import bootstrap_database
from backend.graph import GraphBuilder
from backend.indexer import rebuild_vector_index
from backend.ingest import run_ingest
from backend.pagerank import run_pagerank
from backend.searcher import SearchService
from backend.types import SearchParams


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="DocumentWho CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    ingest = subparsers.add_parser("ingest")
    ingest.add_argument("--source-dir", default=None)

    subparsers.add_parser("pagerank")
    subparsers.add_parser("rebuild-indexes")

    search = subparsers.add_parser("search")
    search.add_argument("query")
    search.add_argument("--top-k", type=int, default=5)
    search.add_argument("--ext", default=None)
    search.add_argument("--language", default=None)
    search.add_argument("--entity", default=None)
    search.add_argument("--tag", default=None)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    bootstrap_database()

    if args.command == "ingest":
        stats, duration = run_ingest(None if args.source_dir is None else Path(args.source_dir).resolve())
        print(json.dumps({"duration_seconds": duration, **asdict(stats)}, indent=2))
        return
    if args.command == "pagerank":
        print(json.dumps(run_pagerank(), indent=2))
        return
    if args.command == "rebuild-indexes":
        vector_stats = rebuild_vector_index()
        graph_stats = GraphBuilder().rebuild()
        pagerank = run_pagerank()
        print(
            json.dumps(
                {
                    "vector": asdict(vector_stats),
                    "graph": asdict(graph_stats),
                    "pagerank_nodes": len(pagerank),
                },
                indent=2,
            )
        )
        return
    if args.command == "search":
        response = SearchService().search(
            SearchParams(
                query=args.query,
                top_k=args.top_k,
                ext=args.ext,
                language=args.language,
                entity=args.entity,
                tag=args.tag,
                debug=True,
            )
        )
        print(response.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
