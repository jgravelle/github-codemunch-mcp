"""PageRank and centrality utilities for the file import graph."""

from typing import Optional


def compute_pagerank(
    imports: dict,
    source_files: list,
    alias_map: Optional[dict] = None,
    damping: float = 0.85,
    max_iter: int = 100,
    tol: float = 1e-6,
) -> tuple:
    """Compute PageRank on the file import graph.

    Standard PageRank with damping=0.85 and dangling-node correction.
    Scores are normalized so they sum to approximately 1.0.

    Returns:
        (scores: dict[str, float], iterations_to_converge: int)
    """
    from ..parser.imports import resolve_specifier

    source_file_set = frozenset(source_files)
    n = len(source_files)
    if n == 0:
        return {}, 0

    # Build directed adjacency lists from import graph
    out_links: dict = {f: [] for f in source_files}
    in_links: dict = {f: [] for f in source_files}

    for src_file, file_imports in (imports or {}).items():
        if src_file not in source_file_set:
            continue
        seen: set = set()
        for imp in file_imports:
            target = resolve_specifier(imp["specifier"], src_file, source_file_set, alias_map)
            if target and target != src_file and target in source_file_set and target not in seen:
                seen.add(target)
                out_links[src_file].append(target)
                in_links[target].append(src_file)

    # Initialize uniform distribution
    scores: dict = {f: 1.0 / n for f in source_files}

    for iteration in range(max_iter):
        # Dangling-node mass: files with no outbound links redistribute to all
        dangling_sum = sum(scores[f] for f in source_files if not out_links[f])
        dangling_per_node = damping * dangling_sum / n

        new_scores: dict = {}
        for f in source_files:
            rank_sum = 0.0
            for src in in_links[f]:
                out_count = len(out_links[src])
                if out_count > 0:
                    rank_sum += scores[src] / out_count
            new_scores[f] = (1.0 - damping) / n + damping * rank_sum + dangling_per_node

        delta = sum(abs(new_scores[f] - scores[f]) for f in source_files)
        scores = new_scores
        if delta < tol:
            return scores, iteration + 1

    return scores, max_iter


def compute_in_out_degrees(
    imports: dict,
    source_files: list,
    alias_map: Optional[dict] = None,
) -> tuple:
    """Return (in_degree, out_degree) dicts for each file.

    in_degree[f]  = number of indexed files that import f
    out_degree[f] = number of indexed files that f imports
    """
    from ..parser.imports import resolve_specifier

    source_file_set = frozenset(source_files)
    in_deg: dict = {f: 0 for f in source_files}
    out_deg: dict = {f: 0 for f in source_files}

    for src_file, file_imports in (imports or {}).items():
        if src_file not in source_file_set:
            continue
        seen: set = set()
        for imp in file_imports:
            target = resolve_specifier(imp["specifier"], src_file, source_file_set, alias_map)
            if target and target != src_file and target in source_file_set and target not in seen:
                seen.add(target)
                in_deg[target] = in_deg.get(target, 0) + 1
                out_deg[src_file] = out_deg.get(src_file, 0) + 1

    return in_deg, out_deg
