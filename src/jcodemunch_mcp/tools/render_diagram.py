"""render_diagram — universal Mermaid renderer for every graph-producing tool.

Accepts the raw output dict from any of jCodeMunch's graph tools and
auto-detects the source to pick the optimal diagram type, encode metadata
as visual signals (edge confidence, risk heat, cohesion borders, drifter
callouts), and apply a theme.

Supported sources:
  get_call_hierarchy   → flowchart TD  (callers above, callees below)
  get_signal_chains    → sequenceDiagram (gateway-to-leaf sequential flow)
  get_tectonic_map     → flowchart LR  (subgraph clusters per plate)
  get_dependency_cycles→ flowchart LR  (cycle edges highlighted)
  get_impact_preview   → flowchart BT  (target at bottom, impact ripples up)
  get_blast_radius     → flowchart TD  (concentric depth-ring subgraphs)
  get_dependency_graph → flowchart LR  (directed import edges)
"""

from __future__ import annotations

import re
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Theme system
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Palette:
    """Visual palette for Mermaid classDef / linkStyle generation."""

    depth_fills: tuple[str, ...]       # gradient by depth (0, 1, 2, 3+)
    edge_confidence: dict[str, str]    # resolution tier → stroke color
    edge_dash: dict[str, str]          # resolution tier → stroke-dasharray
    risk_fills: dict[str, str]         # "high"/"medium"/"low" → fill
    accent: str                        # primary highlight
    dimmed: str                        # de-emphasized
    text: str                          # label color
    bg: str                            # background hint


_PALETTE_FLOW = Palette(
    depth_fills=("#4A90D9", "#7B68EE", "#9370DB", "#BA55D3"),
    edge_confidence={
        "lsp_dispatch": "#2ECC40",
        "lsp_resolved": "#2ECC40",
        "ast_resolved": "#0074D9",
        "ast_inferred": "#FF851B",
        "text_matched": "#FF4136",
    },
    edge_dash={
        "lsp_dispatch": "0",
        "lsp_resolved": "0",
        "ast_resolved": "0",
        "ast_inferred": "5 5",
        "text_matched": "2 2",
    },
    risk_fills={"high": "#FF4136", "medium": "#FF851B", "low": "#2ECC40"},
    accent="#4A90D9",
    dimmed="#94A3B8",
    text="#fff",
    bg="#0a0e1a",
)

_PALETTE_RISK = Palette(
    depth_fills=("#FF4136", "#FF851B", "#FFDC00", "#2ECC40"),
    edge_confidence={
        "lsp_dispatch": "#2ECC40",
        "lsp_resolved": "#2ECC40",
        "ast_resolved": "#0074D9",
        "ast_inferred": "#FF851B",
        "text_matched": "#FF4136",
    },
    edge_dash={
        "lsp_dispatch": "0",
        "lsp_resolved": "0",
        "ast_resolved": "0",
        "ast_inferred": "5 5",
        "text_matched": "2 2",
    },
    risk_fills={"high": "#FF4136", "medium": "#FF851B", "low": "#2ECC40"},
    accent="#FF4136",
    dimmed="#94A3B8",
    text="#fff",
    bg="#1a0a0a",
)

_PALETTE_MINIMAL = Palette(
    depth_fills=("#F5F5F5", "#E0E0E0", "#CCCCCC", "#B0B0B0"),
    edge_confidence={
        "lsp_dispatch": "#333",
        "lsp_resolved": "#333",
        "ast_resolved": "#666",
        "ast_inferred": "#666",
        "text_matched": "#999",
    },
    edge_dash={
        "lsp_dispatch": "0",
        "lsp_resolved": "0",
        "ast_resolved": "0",
        "ast_inferred": "5 5",
        "text_matched": "2 2",
    },
    risk_fills={"high": "#999", "medium": "#BBB", "low": "#DDD"},
    accent="#333",
    dimmed="#CCC",
    text="#333",
    bg="#fff",
)

_PALETTES: dict[str, Palette] = {
    "flow": _PALETTE_FLOW,
    "risk": _PALETTE_RISK,
    "minimal": _PALETTE_MINIMAL,
}


# ---------------------------------------------------------------------------
# Sanitisation helpers
# ---------------------------------------------------------------------------

_UNSAFE_RE = re.compile(r"[^a-zA-Z0-9_]")


def _node_id(index: int) -> str:
    """Short sequential node ID safe for Mermaid."""
    return f"nd{index}"


def _sanitize_label(text: str) -> str:
    """Escape characters that break Mermaid label strings."""
    return text.replace('"', "'").replace("<", "&lt;").replace(">", "&gt;")


def _basename(path: str) -> str:
    """Strip to filename only, forward-slash normalised."""
    return path.replace("\\", "/").rsplit("/", 1)[-1]


def _disambiguate_basenames(paths: list[str]) -> dict[str, str]:
    """Map each path to a short display name, disambiguating collisions."""
    base_map: dict[str, list[str]] = defaultdict(list)
    for p in paths:
        base_map[_basename(p)].append(p)

    display: dict[str, str] = {}
    for base, sources in base_map.items():
        if len(sources) == 1:
            display[sources[0]] = base
        else:
            for s in sources:
                parts = s.replace("\\", "/").split("/")
                suffix = "/".join(parts[-2:]) if len(parts) >= 2 else base
                display[s] = suffix
    return display


# ---------------------------------------------------------------------------
# Pruning
# ---------------------------------------------------------------------------

def _prune_graph(
    nodes: list[str],
    edges: list[tuple[str, str]],
    max_nodes: int,
    preserve: set[str],
) -> tuple[list[str], list[tuple[str, str]], int]:
    """Smart graph pruning: leaves first, then depth collapse.

    Returns (remaining_nodes, remaining_edges, pruned_count).
    """
    if len(nodes) <= max_nodes:
        return nodes, edges, 0

    node_set = set(nodes)
    edge_set = list(edges)
    pruned = 0

    # Phase 1: iteratively remove leaf nodes (degree 1)
    changed = True
    while changed and len(node_set) > max_nodes:
        changed = False
        degree: dict[str, int] = defaultdict(int)
        for a, b in edge_set:
            if a in node_set:
                degree[a] += 1
            if b in node_set:
                degree[b] += 1

        leaves = [
            n for n in node_set
            if degree.get(n, 0) <= 1 and n not in preserve
        ]
        if not leaves:
            break

        for leaf in leaves:
            if len(node_set) <= max_nodes:
                break
            node_set.discard(leaf)
            pruned += 1
            changed = True

        edge_set = [(a, b) for a, b in edge_set if a in node_set and b in node_set]

    # Phase 2: if still over, remove nodes with lowest degree (non-preserve)
    if len(node_set) > max_nodes:
        degree: dict[str, int] = defaultdict(int)
        for a, b in edge_set:
            if a in node_set:
                degree[a] += 1
            if b in node_set:
                degree[b] += 1

        removable = sorted(
            [n for n in node_set if n not in preserve],
            key=lambda n: degree.get(n, 0),
        )
        while len(node_set) > max_nodes and removable:
            node_set.discard(removable.pop(0))
            pruned += 1
        edge_set = [(a, b) for a, b in edge_set if a in node_set and b in node_set]

    return sorted(node_set), edge_set, pruned


# ---------------------------------------------------------------------------
# Source auto-detection
# ---------------------------------------------------------------------------

_SOURCE_SIGNATURES: list[tuple[str, set[str]]] = [
    ("tectonic_map", {"plates", "plate_count"}),
    ("signal_chains_discovery", {"chains", "gateway_count", "orphan_symbols"}),
    ("signal_chains_lookup", {"chains", "on_no_chain"}),
    ("impact_preview", {"affected_symbols", "call_chains"}),
    ("dependency_cycles", {"cycles", "cycle_count"}),
    ("call_hierarchy", {"symbol", "callers", "callees"}),
    ("blast_radius", {"confirmed", "symbol"}),
    ("dependency_graph", {"neighbors", "file"}),
]


def _detect_source(source: dict) -> str:
    """Identify which tool produced *source* by its key signature."""
    if "error" in source and len(source) <= 2:
        return "error"

    keys = set(source.keys())
    for name, required in _SOURCE_SIGNATURES:
        if required.issubset(keys):
            return name

    # call_hierarchy: callers OR callees suffices (direction may omit one)
    if "symbol" in keys and ("callers" in keys or "callees" in keys):
        return "call_hierarchy"

    return "unknown"


# ---------------------------------------------------------------------------
# Per-source renderers
# ---------------------------------------------------------------------------

def _render_call_hierarchy(source: dict, pal: Palette, max_nodes: int) -> dict:
    """Flowchart TD — callers above root, callees below, confidence-colored edges."""
    lines: list[str] = ["flowchart TD"]
    edge_styles: list[tuple[int, str, str]] = []  # (edge_index, color, dash)
    edge_idx = 0
    node_map: dict[str, str] = {}  # symbol_id → node_id
    nid = 0

    sym = source.get("symbol", {})
    root_label = _sanitize_label(sym.get("name", "?"))
    root_id = _node_id(nid)
    node_map[sym.get("id", "__root__")] = root_id
    nid += 1

    # classDefs
    lines.append(f'  classDef root fill:{pal.accent},stroke:#333,stroke-width:3px,color:{pal.text}')
    for tier, color in pal.edge_confidence.items():
        dash = pal.edge_dash.get(tier, "0")
        if dash == "0":
            lines.append(f'  classDef edge_{tier} stroke:{color},stroke-width:2px')
        else:
            lines.append(f'  classDef edge_{tier} stroke:{color},stroke-dasharray:{dash}')

    # Shapes by kind
    kind_shapes = {
        "function": ('["', '"]'),
        "class": ('(["', '"])'),
        "method": ('[["', '"]]'),
    }
    default_shape = ('["', '"]')

    def _shape(kind: str) -> tuple[str, str]:
        return kind_shapes.get(kind, default_shape)

    # Root node
    lp, rp = _shape(sym.get("kind", "function"))
    lines.append(f'  {root_id}{lp}{root_label}{rp}:::root')

    # Collect all paths for disambiguation
    all_files: list[str] = []
    for c in source.get("callers", []):
        f = c.get("file", "")
        if f:
            all_files.append(f)
    for c in source.get("callees", []):
        f = c.get("file", "")
        if f:
            all_files.append(f)
    display = _disambiguate_basenames(all_files)

    # Group callers/callees by file for subgraphs
    callers_by_file: dict[str, list[dict]] = defaultdict(list)
    for c in source.get("callers", []):
        callers_by_file[c.get("file", "unknown")].append(c)

    callees_by_file: dict[str, list[dict]] = defaultdict(list)
    for c in source.get("callees", []):
        callees_by_file[c.get("file", "unknown")].append(c)

    # Pruning: collect all nodes/edges, prune, then render only survivors
    all_sym_ids = [sym.get("id", "__root__")]
    all_edges: list[tuple[str, str]] = []
    for c in source.get("callers", []):
        cid = c.get("id", f"caller_{nid}")
        all_sym_ids.append(cid)
        all_edges.append((cid, sym.get("id", "__root__")))
    for c in source.get("callees", []):
        cid = c.get("id", f"callee_{nid}")
        all_sym_ids.append(cid)
        all_edges.append((sym.get("id", "__root__"), cid))

    survivors, surviving_edges, pruned = _prune_graph(
        all_sym_ids, all_edges, max_nodes, {sym.get("id", "__root__")}
    )
    survivor_set = set(survivors)
    surviving_edge_set = set(surviving_edges)

    # Render callers
    for fpath, syms in callers_by_file.items():
        filtered = [s for s in syms if s.get("id", "") in survivor_set]
        if not filtered:
            continue
        file_label = _sanitize_label(display.get(fpath, _basename(fpath)))
        sg_id = f"sg_c{nid}"
        nid += 1
        lines.append(f'  subgraph {sg_id}["{file_label}"]')
        for s in filtered:
            sid = s.get("id", f"c{nid}")
            nid_str = _node_id(nid)
            node_map[sid] = nid_str
            nid += 1
            lp, rp = _shape(s.get("kind", "function"))
            lines.append(f'    {nid_str}{lp}{_sanitize_label(s.get("name", "?"))}{rp}')
        lines.append("  end")

    # Render callees
    for fpath, syms in callees_by_file.items():
        filtered = [s for s in syms if s.get("id", "") in survivor_set]
        if not filtered:
            continue
        file_label = _sanitize_label(display.get(fpath, _basename(fpath)))
        sg_id = f"sg_e{nid}"
        nid += 1
        lines.append(f'  subgraph {sg_id}["{file_label}"]')
        for s in filtered:
            sid = s.get("id", f"e{nid}")
            nid_str = _node_id(nid)
            node_map[sid] = nid_str
            nid += 1
            lp, rp = _shape(s.get("kind", "function"))
            lines.append(f'    {nid_str}{lp}{_sanitize_label(s.get("name", "?"))}{rp}')
        lines.append("  end")

    # Edges with confidence styling
    for a, b in surviving_edges:
        a_nd = node_map.get(a)
        b_nd = node_map.get(b)
        if not a_nd or not b_nd:
            continue
        # Find resolution tier for this edge
        resolution = "text_matched"
        for c in source.get("callers", []) + source.get("callees", []):
            if c.get("id") in (a, b):
                resolution = c.get("resolution", "text_matched")
                break
        color = pal.edge_confidence.get(resolution, "#999")
        dash = pal.edge_dash.get(resolution, "0")
        lines.append(f'  {a_nd} --> {b_nd}')
        style_parts = [f"stroke:{color}"]
        if dash != "0":
            style_parts.append(f"stroke-dasharray:{dash}")
        else:
            style_parts.append("stroke-width:2px")
        edge_styles.append((edge_idx, color, dash))
        edge_idx += 1

    # Apply linkStyles
    for idx, color, dash in edge_styles:
        parts = [f"stroke:{color}"]
        if dash != "0":
            parts.append(f"stroke-dasharray:{dash}")
        else:
            parts.append("stroke-width:2px")
        lines.append(f"  linkStyle {idx} {','.join(parts)}")

    node_count = len([n for n in survivor_set if n in node_map])
    legend = (
        "Edge color: green=LSP-resolved, blue=AST-resolved, orange=AST-inferred, red=text-heuristic\n"
        "Edge dash: solid=compiler-grade, dashed=inferred, dotted=heuristic\n"
        "Node shape: rectangle=function, stadium=class, subroutine=method\n"
        "Root node: highlighted (the queried symbol)\n"
        "Grouped by: source file"
    )
    return {
        "diagram_type": "flowchart TD",
        "mermaid": "\n".join(lines),
        "node_count": node_count,
        "edge_count": len(surviving_edges),
        "pruned_count": pruned,
        "legend": legend,
    }


def _render_signal_chains(source: dict, pal: Palette, max_nodes: int) -> dict:
    """SequenceDiagram — gateway-to-leaf sequential flow, grouped by kind."""
    lines: list[str] = ["sequenceDiagram"]
    chains = source.get("chains", [])
    if not chains:
        lines.append("  Note over System: No signal chains detected")
        return {
            "diagram_type": "sequenceDiagram",
            "mermaid": "\n".join(lines),
            "node_count": 0,
            "edge_count": 0,
            "pruned_count": 0,
            "legend": "No gateways detected in this codebase.",
        }

    # Budget: limit chains per kind to fit max_nodes
    max_participants = max_nodes
    max_chains_per_kind = max(1, max_participants // max(len(chains), 1))

    # Group chains by kind
    by_kind: dict[str, list[dict]] = defaultdict(list)
    for c in chains:
        by_kind[c.get("kind", "unknown")].append(c)

    # Sort each group by reach descending, cap
    pruned = 0
    selected_chains: list[dict] = []
    for kind in ("http", "cli", "task", "event", "main", "test"):
        group = by_kind.get(kind, [])
        group.sort(key=lambda c: -c.get("reach", 0))
        cap = min(len(group), max(3, max_chains_per_kind))
        selected_chains.extend(group[:cap])
        pruned += max(0, len(group) - cap)

    # Collect unique symbol names as participants (preserving first-seen order)
    seen_participants: dict[str, int] = {}
    pid = 0
    for chain in selected_chains:
        for sym_name in chain.get("symbols", []):
            if sym_name not in seen_participants:
                seen_participants[sym_name] = pid
                pid += 1
                if pid >= max_participants:
                    break
        if pid >= max_participants:
            break

    # Render kind boxes and participants
    kind_colors = {
        "http": "rgb(173,216,230)",
        "cli": "rgb(255,228,196)",
        "task": "rgb(216,191,216)",
        "event": "rgb(193,225,193)",
        "main": "rgb(211,211,211)",
        "test": "rgb(255,218,185)",
    }

    # Group participants by their gateway kind
    gw_names_by_kind: dict[str, list[str]] = defaultdict(list)
    for chain in selected_chains:
        gw_name = chain.get("gateway_name", "")
        kind = chain.get("kind", "unknown")
        if gw_name and gw_name not in gw_names_by_kind[kind]:
            gw_names_by_kind[kind].append(gw_name)

    # Emit participant boxes by kind
    emitted_participants: set[str] = set()
    for kind in ("http", "cli", "task", "event", "main", "test"):
        gw_names = gw_names_by_kind.get(kind, [])
        if not gw_names:
            continue
        color = kind_colors.get(kind, "rgb(200,200,200)")
        lines.append(f"  box {color} {kind.upper()}")
        for gw in gw_names:
            safe_alias = _UNSAFE_RE.sub("_", gw)
            label = _sanitize_label(gw)
            lines.append(f'    participant {safe_alias} as "{label}"')
            emitted_participants.add(gw)
        lines.append("  end")

    # Emit non-gateway participants
    for sym_name in seen_participants:
        if sym_name not in emitted_participants:
            safe_alias = _UNSAFE_RE.sub("_", sym_name)
            lines.append(f'  participant {safe_alias} as "{_sanitize_label(sym_name)}"')
            emitted_participants.add(sym_name)

    # Render chain messages
    edge_count = 0
    for chain in selected_chains:
        symbols = chain.get("symbols", [])
        label = chain.get("label", chain.get("gateway_name", ""))
        if len(symbols) < 2:
            continue
        lines.append(f"  Note over {_UNSAFE_RE.sub('_', symbols[0])}: {_sanitize_label(label)}")
        for i in range(len(symbols) - 1):
            if symbols[i] not in seen_participants or symbols[i + 1] not in seen_participants:
                continue
            src = _UNSAFE_RE.sub("_", symbols[i])
            dst = _UNSAFE_RE.sub("_", symbols[i + 1])
            lines.append(f"  {src}->>+{dst}: calls")
            edge_count += 1

    # Orphan stats as trailing note
    orphan_pct = source.get("orphan_symbol_pct", 0)
    if orphan_pct > 0:
        lines.append(f"  Note right of {_UNSAFE_RE.sub('_', selected_chains[0].get('gateway_name', 'System'))}: {orphan_pct}% orphan symbols")

    legend = (
        "Participants: functions/methods in call order (left to right)\n"
        "Colored boxes: gateway kind (HTTP=blue, CLI=peach, Task=purple, Event=green)\n"
        "Arrows: call relationships along the signal chain\n"
        "Notes: route/command labels and orphan percentage"
    )
    return {
        "diagram_type": "sequenceDiagram",
        "mermaid": "\n".join(lines),
        "node_count": len(emitted_participants),
        "edge_count": edge_count,
        "pruned_count": pruned,
        "legend": legend,
    }


def _render_tectonic_map(source: dict, pal: Palette, max_nodes: int) -> dict:
    """Flowchart LR — subgraph clusters per plate with cohesion and coupling."""
    lines: list[str] = ["flowchart LR"]
    lines.append(f"  classDef anchor fill:{pal.accent},stroke:#333,stroke-width:3px,color:{pal.text}")
    lines.append(f"  classDef drifter fill:#FF851B,stroke:#333,color:{pal.text}")
    lines.append(f"  classDef nexus stroke:#FF4136,stroke-width:4px")
    lines.append(f"  classDef isolated fill:{pal.dimmed},stroke:#999,color:#666")

    plates = source.get("plates", [])
    node_count = 0
    edge_count = 0
    pruned = 0
    nid = 0

    plate_anchor_nodes: dict[int, str] = {}  # plate_id → node_id of anchor
    anchor_lookup: dict[str, str] = {}        # anchor file path → node_id

    for plate in plates:
        pid = plate.get("plate_id", nid)
        anchor = plate.get("anchor", "")
        cohesion = plate.get("cohesion", 0)
        majority_dir = plate.get("majority_directory", "?")
        files = plate.get("files", [])
        drifters = set(plate.get("drifters", []))
        is_nexus = plate.get("nexus_alert", False)

        # Cap files per plate for readability
        max_per_plate = max(5, max_nodes // max(len(plates), 1))
        shown_files = files[:max_per_plate]
        if len(files) > max_per_plate:
            pruned += len(files) - max_per_plate

        nexus_tag = " ⚠ NEXUS" if is_nexus else ""
        sg_label = _sanitize_label(f"{majority_dir} (cohesion: {cohesion:.2f}){nexus_tag}")
        sg_id = f"plate{pid}"
        lines.append(f'  subgraph {sg_id}["{sg_label}"]')

        for fpath in shown_files:
            nd = _node_id(nid)
            nid += 1
            node_count += 1
            label = _sanitize_label(_basename(fpath))
            if fpath == anchor:
                lines.append(f'    {nd}["{label}"]:::anchor')
                plate_anchor_nodes[pid] = nd
                anchor_lookup[fpath] = nd
            elif fpath in drifters:
                lines.append(f'    {nd}["{label}"]:::drifter')
            else:
                lines.append(f'    {nd}["{label}"]')

        if len(files) > max_per_plate:
            overflow_nd = _node_id(nid)
            nid += 1
            node_count += 1
            lines.append(f'    {overflow_nd}[/"...+{len(files) - max_per_plate} more"/]:::isolated')

        lines.append("  end")

    # Coupling edges between plates (anchor-to-anchor)
    for plate in plates:
        pid = plate.get("plate_id", 0)
        src_nd = plate_anchor_nodes.get(pid)
        if not src_nd:
            continue
        for target_ref, weight in (plate.get("coupled_to") or {}).items():
            # target_ref may be an anchor file path or a plate_id string
            tgt_nd = anchor_lookup.get(target_ref)
            if not tgt_nd:
                # Try matching by plate_id
                try:
                    tgt_nd = plate_anchor_nodes.get(int(target_ref))
                except (ValueError, TypeError):
                    pass
            if tgt_nd and src_nd != tgt_nd:
                thickness = max(1, min(6, int(weight * 8)))
                lines.append(f"  {src_nd} ---|{weight:.2f}| {tgt_nd}")
                edge_count += 1

    # Isolated files
    isolated = source.get("isolated_files", [])
    if isolated:
        iso_shown = isolated[:5]
        lines.append('  subgraph iso["Isolated"]')
        for fpath in iso_shown:
            nd = _node_id(nid)
            nid += 1
            node_count += 1
            lines.append(f'    {nd}["{_sanitize_label(_basename(fpath))}"]:::isolated')
        if len(isolated) > 5:
            nd = _node_id(nid)
            nid += 1
            lines.append(f'    {nd}[/"...+{len(isolated) - 5} more"/]:::isolated')
        lines.append("  end")

    legend = (
        "Subgraphs: logical modules (plates) discovered by coupling analysis\n"
        "Cohesion score: intra-plate density (0.0-1.0) shown in title\n"
        "Anchor node: highlighted (highest internal connectivity)\n"
        "Drifter: orange fill (file directory doesn't match logical module)\n"
        "NEXUS: red border (coupled to 4+ other plates — god-module risk)\n"
        "Edge labels: inter-plate coupling weight"
    )
    return {
        "diagram_type": "flowchart LR",
        "mermaid": "\n".join(lines),
        "node_count": node_count,
        "edge_count": edge_count,
        "pruned_count": pruned,
        "legend": legend,
    }


def _render_dependency_cycles(source: dict, pal: Palette, max_nodes: int) -> dict:
    """Flowchart LR — each SCC in a subgraph, cycle edges red."""
    lines: list[str] = ["flowchart LR"]
    lines.append(f"  classDef cycled fill:#FFE0E0,stroke:#FF4136,stroke-width:2px")
    lines.append(f"  classDef clean fill:#E0FFE0,stroke:#2ECC40")

    cycles = source.get("cycles", [])
    if not cycles:
        lines.append('  none["No circular dependencies detected ✓"]:::clean')
        return {
            "diagram_type": "flowchart LR",
            "mermaid": "\n".join(lines),
            "node_count": 1,
            "edge_count": 0,
            "pruned_count": 0,
            "legend": "No circular import chains found.",
        }

    nid = 0
    node_count = 0
    edge_count = 0
    pruned = 0
    file_to_node: dict[str, str] = {}

    # Disambiguate all files across all cycles
    all_files = [f for cycle in cycles for f in cycle]
    display = _disambiguate_basenames(all_files)

    for ci, cycle in enumerate(cycles):
        if node_count >= max_nodes:
            pruned += sum(len(c) for c in cycles[ci:])
            break

        sg_label = _sanitize_label(f"Cycle {ci + 1} ({len(cycle)} files)")
        lines.append(f'  subgraph cyc{ci}["{sg_label}"]')

        cycle_nodes: list[str] = []
        for fpath in cycle:
            if fpath not in file_to_node:
                nd = _node_id(nid)
                nid += 1
                node_count += 1
                file_to_node[fpath] = nd
                label = _sanitize_label(display.get(fpath, _basename(fpath)))
                lines.append(f'    {nd}["{label}"]:::cycled')
            cycle_nodes.append(file_to_node[fpath])

        lines.append("  end")

        # Cycle edges: consecutive + closing edge back to first
        for i in range(len(cycle_nodes)):
            src = cycle_nodes[i]
            dst = cycle_nodes[(i + 1) % len(cycle_nodes)]
            if src != dst:
                lines.append(f"  {src} --> {dst}")
                edge_count += 1

    # Style all cycle edges red
    for i in range(edge_count):
        lines.append(f"  linkStyle {i} stroke:#FF4136,stroke-width:2px")

    legend = (
        "Each subgraph: one strongly-connected component (circular import chain)\n"
        "Red nodes: files involved in a cycle\n"
        "Red edges: import direction within the cycle\n"
        "Cycle edges shown as consecutive ring (simplified from full SCC)"
    )
    return {
        "diagram_type": "flowchart LR",
        "mermaid": "\n".join(lines),
        "node_count": node_count,
        "edge_count": edge_count,
        "pruned_count": pruned,
        "legend": legend,
    }


def _render_impact_preview(source: dict, pal: Palette, max_nodes: int) -> dict:
    """Flowchart BT — target at bottom, impact ripples upward through call chains."""
    lines: list[str] = ["flowchart BT"]
    lines.append(f"  classDef target fill:{pal.accent},stroke:#333,stroke-width:4px,color:{pal.text}")

    # Depth colors
    depth_colors = list(pal.depth_fills) + [pal.depth_fills[-1]] * 5
    for d in range(min(5, len(depth_colors))):
        lines.append(f"  classDef d{d + 1} fill:{depth_colors[d]},color:{pal.text}")

    sym = source.get("symbol", {})
    affected = source.get("affected_symbols", [])

    # Pruning
    all_ids = [sym.get("id", "__target__")] + [a.get("id", "") for a in affected]
    all_edges: list[tuple[str, str]] = []
    for a in affected:
        chain = a.get("call_chain", [])
        if len(chain) >= 2:
            all_edges.append((chain[-2], chain[-1]))

    survivors, surviving_edges, pruned = _prune_graph(
        all_ids, all_edges, max_nodes, {sym.get("id", "__target__")}
    )
    survivor_set = set(survivors)

    nid = 0
    node_map: dict[str, str] = {}

    # Target node
    root_nd = _node_id(nid)
    nid += 1
    node_map[sym.get("id", "__target__")] = root_nd
    root_label = _sanitize_label(sym.get("name", "?"))
    lines.append(f'  {root_nd}["{root_label}"]:::target')

    # Affected symbols grouped by file
    by_file: dict[str, list[dict]] = defaultdict(list)
    for a in affected:
        if a.get("id", "") in survivor_set:
            by_file[a.get("file", "unknown")].append(a)

    display = _disambiguate_basenames(list(by_file.keys()))

    for fpath, syms in by_file.items():
        file_label = _sanitize_label(display.get(fpath, _basename(fpath)))
        sg_id = f"sg{nid}"
        nid += 1
        lines.append(f'  subgraph {sg_id}["{file_label}"]')
        for s in syms:
            nd = _node_id(nid)
            nid += 1
            node_map[s["id"]] = nd
            chain_len = len(s.get("call_chain", []))
            depth_class = f"d{min(chain_len, 5)}" if chain_len > 0 else "d1"
            lines.append(f'    {nd}["{_sanitize_label(s.get("name", "?"))}"]:::{depth_class}')
        lines.append("  end")

    # Edges from call chains
    edge_count = 0
    for a, b in surviving_edges:
        a_nd = node_map.get(a)
        b_nd = node_map.get(b)
        if a_nd and b_nd:
            lines.append(f"  {a_nd} --> {b_nd}")
            edge_count += 1

    legend = (
        "Target node: highlighted at bottom (the symbol being removed/renamed)\n"
        f"Depth colors: gradient from depth 1 to 5 (deeper = more indirect impact)\n"
        "Arrows: call chain direction (caller → callee)\n"
        "Grouped by: source file"
    )
    return {
        "diagram_type": "flowchart BT",
        "mermaid": "\n".join(lines),
        "node_count": len(node_map),
        "edge_count": edge_count,
        "pruned_count": pruned,
        "legend": legend,
    }


def _render_blast_radius(source: dict, pal: Palette, max_nodes: int) -> dict:
    """Flowchart TD — concentric depth-ring subgraphs around target."""
    lines: list[str] = ["flowchart TD"]
    lines.append(f"  classDef target fill:{pal.accent},stroke:#333,stroke-width:4px,color:{pal.text}")
    lines.append(f"  classDef confirmed fill:#FFE0E0,stroke:#FF4136")
    lines.append(f"  classDef potential fill:#FFF3E0,stroke:#FF851B,stroke-dasharray:5 5")
    lines.append(f"  classDef cross fill:#E0E0FF,stroke:#0074D9,stroke-dasharray:8 4")

    sym = source.get("symbol", "")
    if isinstance(sym, dict):
        sym_name = sym.get("name", str(sym))
    else:
        sym_name = str(sym)

    nid = 0
    root_nd = _node_id(nid)
    nid += 1
    lines.append(f'  {root_nd}["{_sanitize_label(sym_name)}"]:::target')

    confirmed = source.get("confirmed", [])
    potential = source.get("potential", [])
    node_count = 1
    edge_count = 0
    pruned = 0

    # Confirmed files — group by depth if available
    impact_by_depth = source.get("impact_by_depth", {})
    if impact_by_depth:
        for depth_str in sorted(impact_by_depth.keys(), key=lambda x: int(x)):
            depth_files = impact_by_depth[depth_str]
            sg_label = _sanitize_label(f"Depth {depth_str} — {'Direct' if depth_str == '1' else 'Transitive'}")
            sg_id = f"depth{depth_str}"
            lines.append(f'  subgraph {sg_id}["{sg_label}"]')
            for finfo in depth_files:
                fpath = finfo if isinstance(finfo, str) else finfo.get("file", str(finfo))
                nd = _node_id(nid)
                nid += 1
                node_count += 1
                label = _sanitize_label(_basename(fpath))
                lines.append(f'    {nd}["{label}"]:::confirmed')
                lines.append(f"  {root_nd} --> {nd}")
                edge_count += 1
            lines.append("  end")
    else:
        # Flat confirmed list
        if confirmed:
            shown = confirmed[:max_nodes - 1]
            pruned += max(0, len(confirmed) - len(shown))
            lines.append('  subgraph conf["Direct Impact"]')
            for finfo in shown:
                fpath = finfo if isinstance(finfo, str) else finfo.get("file", str(finfo))
                nd = _node_id(nid)
                nid += 1
                node_count += 1
                label = _sanitize_label(_basename(fpath))
                ref_count = ""
                if isinstance(finfo, dict) and finfo.get("reference_count"):
                    ref_count = f" ({finfo['reference_count']} refs)"
                lines.append(f'    {nd}["{label}{ref_count}"]:::confirmed')
                lines.append(f"  {root_nd} --> {nd}")
                edge_count += 1
            lines.append("  end")

    # Potential files
    if potential:
        pot_shown = potential[:max(5, max_nodes - node_count)]
        pruned += max(0, len(potential) - len(pot_shown))
        lines.append('  subgraph pot["Potential Impact"]')
        for finfo in pot_shown:
            fpath = finfo if isinstance(finfo, str) else finfo.get("file", str(finfo))
            nd = _node_id(nid)
            nid += 1
            node_count += 1
            label = _sanitize_label(_basename(fpath))
            lines.append(f'    {nd}["{label}"]:::potential')
            lines.append(f"  {root_nd} -.-> {nd}")
            edge_count += 1
        lines.append("  end")

    # Risk score annotation
    risk = source.get("overall_risk_score")
    if risk is not None:
        level = "high" if risk > 0.7 else ("medium" if risk > 0.3 else "low")
        risk_color = pal.risk_fills.get(level, "#999")
        lines.append(f'  risk[/"Risk: {risk:.2f} ({level})"/]')
        lines.append(f"  style risk fill:{risk_color},color:{pal.text}")

    legend = (
        "Target: highlighted center node (the symbol being analysed)\n"
        "Confirmed: solid red border (import + name match)\n"
        "Potential: dashed orange border (import only, e.g. wildcard)\n"
        "Cross-repo: dashed blue border\n"
        "Risk badge: overall impact score with heat coloring"
    )
    return {
        "diagram_type": "flowchart TD",
        "mermaid": "\n".join(lines),
        "node_count": node_count,
        "edge_count": edge_count,
        "pruned_count": pruned,
        "legend": legend,
    }


def _render_dependency_graph(source: dict, pal: Palette, max_nodes: int) -> dict:
    """Flowchart LR — directed import edges with focal file highlighted."""
    lines: list[str] = ["flowchart LR"]
    lines.append(f"  classDef focal fill:{pal.accent},stroke:#333,stroke-width:3px,color:{pal.text}")
    lines.append(f"  classDef cross stroke:#0074D9,stroke-dasharray:8 4")

    focal_file = source.get("file", "")
    neighbors = source.get("neighbors", {})
    direction = source.get("direction", "imports")
    cross_edges = source.get("cross_repo_edges", [])

    all_files = [focal_file] + list(neighbors.keys())
    display = _disambiguate_basenames(all_files)

    nid = 0
    node_map: dict[str, str] = {}
    edge_count = 0
    pruned = 0

    # Pruning
    all_nodes = [focal_file] + list(neighbors.keys())
    all_edge_list: list[tuple[str, str]] = []
    for n in neighbors:
        if direction == "importers":
            all_edge_list.append((n, focal_file))
        else:
            all_edge_list.append((focal_file, n))

    survivors, surviving_edges, pruned = _prune_graph(
        all_nodes, all_edge_list, max_nodes, {focal_file}
    )
    survivor_set = set(survivors)

    # Focal node
    root_nd = _node_id(nid)
    nid += 1
    node_map[focal_file] = root_nd
    lines.append(f'  {root_nd}["{_sanitize_label(display.get(focal_file, _basename(focal_file)))}"]:::focal')

    for fpath in survivors:
        if fpath == focal_file:
            continue
        nd = _node_id(nid)
        nid += 1
        node_map[fpath] = nd
        label = _sanitize_label(display.get(fpath, _basename(fpath)))
        lines.append(f'  {nd}["{label}"]')

    for a, b in surviving_edges:
        a_nd = node_map.get(a)
        b_nd = node_map.get(b)
        if a_nd and b_nd:
            lines.append(f"  {a_nd} --> {b_nd}")
            edge_count += 1

    # Cross-repo edges
    for ce in cross_edges:
        target = ce if isinstance(ce, str) else ce.get("file", str(ce))
        nd = _node_id(nid)
        nid += 1
        label = _sanitize_label(_basename(target))
        lines.append(f'  {nd}["{label}"]:::cross')
        lines.append(f"  {root_nd} -.->|cross-repo| {nd}")
        edge_count += 1

    legend = (
        "Focal node: highlighted (the queried file)\n"
        f"Arrow direction: {'importers → focal' if direction == 'importers' else 'focal → imports'}\n"
        "Dashed blue: cross-repo edges"
    )
    return {
        "diagram_type": "flowchart LR",
        "mermaid": "\n".join(lines),
        "node_count": len(node_map) + len(cross_edges),
        "edge_count": edge_count,
        "pruned_count": pruned,
        "legend": legend,
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def render_diagram(
    source: dict,
    theme: str = "flow",
    max_nodes: int = 80,
    open_in_viewer: bool = False,
) -> dict:
    """Render any graph-producing tool's output as annotated Mermaid markup.

    Auto-detects the source tool from the dict's key signature and picks the
    optimal diagram type (flowchart, sequence diagram, or subgraph clusters).
    Encodes metadata as visual signals: edge colors for resolution confidence,
    node shapes for symbol kind, subgraph grouping by file/plate/depth.

    Args:
        source:         Raw output dict from any supported graph-producing tool.
        theme:          Visual theme — 'flow' (default), 'risk', or 'minimal'.
        max_nodes:      Maximum nodes before smart pruning (default 80).
        open_in_viewer: When true, also open the mermaid in mmd-viewer (config-gated).

    Returns:
        Dict with diagram_type, mermaid, node_count, edge_count,
        pruned_count, legend, source_tool, and _meta.
    """
    t0 = time.perf_counter()
    max_nodes = max(10, min(200, max_nodes))

    pal = _PALETTES.get(theme, _PALETTE_FLOW)
    detected = _detect_source(source)

    if detected == "error":
        return {"error": "Cannot render diagram from an error response."}

    _RENDERERS = {
        "call_hierarchy": _render_call_hierarchy,
        "signal_chains_discovery": _render_signal_chains,
        "signal_chains_lookup": _render_signal_chains,
        "impact_preview": _render_impact_preview,
        "dependency_cycles": _render_dependency_cycles,
        "tectonic_map": _render_tectonic_map,
        "blast_radius": _render_blast_radius,
        "dependency_graph": _render_dependency_graph,
    }

    renderer = _RENDERERS.get(detected)
    if not renderer:
        return {
            "error": (
                f"Unrecognised source shape (detected: {detected!r}). "
                "Pass the raw output from get_call_hierarchy, get_signal_chains, "
                "get_tectonic_map, get_dependency_cycles, get_impact_preview, "
                "get_blast_radius, or get_dependency_graph."
            )
        }

    result = renderer(source, pal, max_nodes)

    elapsed = (time.perf_counter() - t0) * 1000
    # Normalise source_tool name (strip discovery/lookup suffix)
    source_tool = detected.split("_discovery")[0].split("_lookup")[0]

    result["source_tool"] = source_tool
    result["_meta"] = {
        "timing_ms": round(elapsed, 1),
        "theme": theme,
        "max_nodes": max_nodes,
        "detection_result": detected,
    }

    if open_in_viewer:
        from .. import config as config_module
        if config_module.get("render_diagram_viewer_enabled", False):
            from .mermaid_viewer import open_diagram
            viewer_result = open_diagram(result.get("mermaid", ""))
            if not viewer_result.get("opened"):
                result["viewer_error"] = viewer_result.get("error")
            else:
                result["viewer_path"] = viewer_result["path"]

    return result
