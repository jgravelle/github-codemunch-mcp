"""Benchmark harness for jcodemunch-mcp.

Measures: full index time, incremental reindex time, search time, retrieval time.
Outputs: Markdown table + JSON artifact.
"""

import json
import os
import sys
import tempfile
import time
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from jcodemunch_mcp.parser import parse_file, LANGUAGE_EXTENSIONS
from jcodemunch_mcp.storage import IndexStore
from jcodemunch_mcp.parser.symbols import Symbol


def generate_python_files(count: int, base_dir: Path) -> dict[str, str]:
    """Generate synthetic Python files for benchmarking."""
    files = {}
    for i in range(count):
        name = f"module_{i:04d}.py"
        content = f'''"""Module {i}."""

MAX_VALUE_{i} = {i * 100}

class Service{i}:
    """Service class {i}."""
    def process(self, data: dict) -> dict:
        """Process data."""
        return data

    def validate(self, item: str) -> bool:
        """Validate an item."""
        return len(item) > 0

def helper_{i}(x: int, y: int) -> int:
    """Helper function {i}."""
    return x + y

def transform_{i}(data: list) -> list:
    """Transform data {i}."""
    return [d for d in data if d]
'''
        files[name] = content
        file_path = base_dir / name
        file_path.write_text(content)
    return files


def benchmark_full_index(files: dict[str, str], store: IndexStore) -> dict:
    """Benchmark full indexing."""
    start = time.perf_counter()

    all_symbols = []
    languages = {}
    raw_files = {}
    parsed_files = []

    for path, content in files.items():
        ext = os.path.splitext(path)[1]
        language = LANGUAGE_EXTENSIONS.get(ext)
        if not language:
            continue
        symbols = parse_file(content, path, language)
        if symbols:
            all_symbols.extend(symbols)
            languages[language] = languages.get(language, 0) + 1
            raw_files[path] = content
            parsed_files.append(path)

    store.save_index(
        owner="bench", name="repo",
        source_files=parsed_files,
        symbols=all_symbols,
        raw_files=raw_files,
        languages=languages,
    )

    elapsed = time.perf_counter() - start
    return {
        "operation": "full_index",
        "file_count": len(parsed_files),
        "symbol_count": len(all_symbols),
        "time_seconds": round(elapsed, 3),
    }


def benchmark_search(store: IndexStore) -> dict:
    """Benchmark symbol search."""
    index = store.load_index("bench", "repo")
    if not index:
        return {"operation": "search", "error": "no index"}

    queries = ["process", "validate", "helper", "Service", "transform"]
    times = []

    for q in queries:
        start = time.perf_counter()
        results = index.search(q)
        elapsed = time.perf_counter() - start
        times.append(elapsed)

    avg_ms = (sum(times) / len(times)) * 1000
    return {
        "operation": "search",
        "queries": len(queries),
        "avg_time_ms": round(avg_ms, 2),
        "total_time_ms": round(sum(times) * 1000, 2),
    }


def benchmark_retrieval(store: IndexStore) -> dict:
    """Benchmark symbol retrieval."""
    index = store.load_index("bench", "repo")
    if not index:
        return {"operation": "retrieval", "error": "no index"}

    # Pick first 20 symbols
    symbol_ids = [s["id"] for s in index.symbols[:20]]
    times = []

    for sid in symbol_ids:
        start = time.perf_counter()
        store.get_symbol_content("bench", "repo", sid)
        elapsed = time.perf_counter() - start
        times.append(elapsed)

    avg_ms = (sum(times) / len(times)) * 1000
    return {
        "operation": "retrieval",
        "symbols_retrieved": len(symbol_ids),
        "avg_time_ms": round(avg_ms, 2),
        "total_time_ms": round(sum(times) * 1000, 2),
    }


def main():
    results_dir = Path(__file__).parent / "results"
    results_dir.mkdir(exist_ok=True)

    tiers = [
        ("small", 50),
        ("medium", 200),
    ]

    all_results = []

    for tier_name, file_count in tiers:
        print(f"\n{'='*60}")
        print(f"Tier: {tier_name} ({file_count} files)")
        print(f"{'='*60}")

        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir) / "src"
            base_dir.mkdir()
            store = IndexStore(base_path=tmpdir)

            # Generate files
            files = generate_python_files(file_count, base_dir)

            # Benchmark
            idx_result = benchmark_full_index(files, store)
            idx_result["tier"] = tier_name
            print(f"  Full index: {idx_result['time_seconds']}s "
                  f"({idx_result['symbol_count']} symbols)")

            search_result = benchmark_search(store)
            search_result["tier"] = tier_name
            print(f"  Search avg: {search_result['avg_time_ms']}ms")

            ret_result = benchmark_retrieval(store)
            ret_result["tier"] = tier_name
            print(f"  Retrieval avg: {ret_result['avg_time_ms']}ms")

            all_results.extend([idx_result, search_result, ret_result])

    # Write JSON
    json_path = results_dir / "benchmark_results.json"
    with open(json_path, "w") as f:
        json.dump(all_results, f, indent=2)

    # Write Markdown
    md_path = results_dir / "benchmark_results.md"
    with open(md_path, "w") as f:
        f.write("# Benchmark Results\n\n")
        f.write("| Tier | Operation | Metric | Value |\n")
        f.write("|------|-----------|--------|-------|\n")
        for r in all_results:
            tier = r.get("tier", "")
            op = r.get("operation", "")
            if op == "full_index":
                f.write(f"| {tier} | Full Index | Time | {r['time_seconds']}s |\n")
                f.write(f"| {tier} | Full Index | Files | {r['file_count']} |\n")
                f.write(f"| {tier} | Full Index | Symbols | {r['symbol_count']} |\n")
            elif op == "search":
                f.write(f"| {tier} | Search | Avg Time | {r['avg_time_ms']}ms |\n")
            elif op == "retrieval":
                f.write(f"| {tier} | Retrieval | Avg Time | {r['avg_time_ms']}ms |\n")

    print(f"\nResults written to {json_path} and {md_path}")


if __name__ == "__main__":
    main()
