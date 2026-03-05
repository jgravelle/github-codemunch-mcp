"""Generic AST symbol extractor using tree-sitter."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from tree_sitter_language_pack import get_parser

from .symbols import Symbol, compute_content_hash, make_symbol_id
from .languages import LanguageSpec, LANGUAGE_REGISTRY, resolve_language_alias

RAZOR_EXTENSIONS = {".razor", ".cshtml"}
RAZOR_BLOCK_PATTERN = re.compile(r"@(code|functions)\b", re.IGNORECASE)
PARSER_CACHE: dict[str, object] = {}


@dataclass
class RazorCodeBlock:
    """A C# code block extracted from a Razor file."""

    body: str
    body_start_byte: int
    body_start_line: int


def parse_file(content: str, filename: str, language: str) -> list[Symbol]:
    """Parse source code and extract symbols using tree-sitter.

    Args:
        content: Raw source code.
        filename: File path (for ID generation).
        language: Language name (must resolve to a registry key).

    Returns:
        List of Symbol objects.
    """
    canonical_language = resolve_language_alias(language) or language
    if canonical_language not in LANGUAGE_REGISTRY:
        return []

    spec = LANGUAGE_REGISTRY[canonical_language]

    if (
        canonical_language == "csharp"
        and _normalized_extension(filename) in RAZOR_EXTENSIONS
    ):
        return _parse_razor_file(content, filename, canonical_language, spec)

    parser = _get_parser_for_language(spec.ts_language)
    source_bytes = content.encode("utf-8")
    symbols = _extract_symbols_from_source(
        source_bytes=source_bytes,
        filename=filename,
        language=canonical_language,
        spec=spec,
        parser=parser,
    )
    return _disambiguate_overloads(symbols)


def _normalized_extension(filename: str) -> str:
    filename = filename.lower()
    dot = filename.rfind(".")
    if dot < 0:
        return ""
    return filename[dot:]


def _get_parser_for_language(ts_language: str):
    """Resolve parser source for a given tree-sitter language id."""
    cached = PARSER_CACHE.get(ts_language)
    if cached is not None:
        return cached

    if ts_language == "vb":
        parser = _build_vb_parser()
    else:
        parser = get_parser(ts_language)

    PARSER_CACHE[ts_language] = parser
    return parser


def _build_vb_parser():
    """Build parser for Visual Basic .NET via optional external grammar."""
    try:
        import tree_sitter
        import tree_sitter_tree_sitter_vb_dotnet
    except Exception as exc:
        raise RuntimeError(
            "VB parser unavailable. Install optional .NET support with "
            "`pip install jcodemunch-mcp[dotnet]`. "
            "If no prebuilt wheel is available, install C build tools first."
        ) from exc

    capsule = tree_sitter_tree_sitter_vb_dotnet.language()
    try:
        language_obj = tree_sitter.Language(capsule)
    except Exception:
        language_obj = capsule

    try:
        return tree_sitter.Parser(language_obj)
    except TypeError:
        parser = tree_sitter.Parser()
        if hasattr(parser, "set_language"):
            parser.set_language(language_obj)
        else:
            parser.language = language_obj
        return parser


def _extract_symbols_from_source(
    source_bytes: bytes,
    filename: str,
    language: str,
    spec: LanguageSpec,
    parser,
) -> list[Symbol]:
    tree = parser.parse(source_bytes)
    symbols: list[Symbol] = []
    _walk_tree(
        tree.root_node,
        spec,
        source_bytes,
        filename,
        language,
        symbols,
        None,
    )
    return symbols


def _parse_razor_file(
    content: str,
    filename: str,
    language: str,
    spec: LanguageSpec,
) -> list[Symbol]:
    """Parse `.razor`/`.cshtml` files by extracting @code/@functions blocks."""
    blocks = _extract_razor_code_blocks(content)
    if not blocks:
        return []

    parser = _get_parser_for_language("csharp")
    source_bytes = content.encode("utf-8")
    all_symbols: list[Symbol] = []

    for idx, block in enumerate(blocks, start=1):
        wrapper_name = f"__RazorComponent_{idx}"
        prefix = f"class {wrapper_name} {{\n"
        suffix = "\n}"
        wrapped = f"{prefix}{block.body}{suffix}"
        wrapped_bytes = wrapped.encode("utf-8")

        symbols = _extract_symbols_from_source(
            source_bytes=wrapped_bytes,
            filename=filename,
            language=language,
            spec=spec,
            parser=parser,
        )

        prefix_bytes = len(prefix.encode("utf-8"))
        body_bytes = len(block.body.encode("utf-8"))
        wrapper_prefix = f"{wrapper_name}."
        wrapper_id_prefix = f"{filename}::{wrapper_name}#"

        for symbol in symbols:
            # Ignore synthetic wrapper class itself.
            if symbol.name == wrapper_name and symbol.kind == "class":
                continue

            # Ignore symbols created outside the wrapped body.
            if symbol.byte_offset < prefix_bytes:
                continue
            if symbol.byte_offset >= prefix_bytes + body_bytes:
                continue

            if symbol.qualified_name.startswith(wrapper_prefix):
                symbol.qualified_name = symbol.qualified_name[len(wrapper_prefix):]
            if symbol.parent and symbol.parent.startswith(wrapper_id_prefix):
                symbol.parent = None

            symbol.id = make_symbol_id(filename, symbol.qualified_name, symbol.kind)

            relative_byte = symbol.byte_offset - prefix_bytes
            symbol.byte_offset = block.body_start_byte + relative_byte

            # Wrapped file body starts on line 2.
            symbol.line = block.body_start_line + (symbol.line - 2)
            symbol.end_line = block.body_start_line + (symbol.end_line - 2)
            if symbol.line < 1:
                symbol.line = 1
            if symbol.end_line < symbol.line:
                symbol.end_line = symbol.line

            real_bytes = source_bytes[
                symbol.byte_offset : symbol.byte_offset + symbol.byte_length
            ]
            if real_bytes:
                symbol.content_hash = compute_content_hash(real_bytes)

            all_symbols.append(symbol)

    return _disambiguate_overloads(all_symbols)


def _extract_razor_code_blocks(content: str) -> list[RazorCodeBlock]:
    """Extract Razor C# blocks and map them to byte/line offsets."""
    blocks: list[RazorCodeBlock] = []
    offsets = _build_utf8_offset_table(content)
    cursor = 0

    while True:
        match = RAZOR_BLOCK_PATTERN.search(content, cursor)
        if not match:
            break

        open_brace_idx = _find_next_open_brace(content, match.end())
        if open_brace_idx is None:
            cursor = match.end()
            continue

        close_brace_idx = _find_matching_brace(content, open_brace_idx)
        if close_brace_idx is None:
            cursor = open_brace_idx + 1
            continue

        body_start_char = open_brace_idx + 1
        body_end_char = close_brace_idx
        body_text = content[body_start_char:body_end_char]
        body_start_byte = offsets[body_start_char]
        body_start_line = _line_from_char_offset(content, body_start_char)

        blocks.append(
            RazorCodeBlock(
                body=body_text,
                body_start_byte=body_start_byte,
                body_start_line=body_start_line,
            )
        )
        cursor = close_brace_idx + 1

    return blocks


def _build_utf8_offset_table(content: str) -> list[int]:
    """Build char-index -> byte-offset map for UTF-8 strings."""
    offsets = [0]
    total = 0
    for ch in content:
        total += len(ch.encode("utf-8"))
        offsets.append(total)
    return offsets


def _line_from_char_offset(content: str, offset: int) -> int:
    return content.count("\n", 0, offset) + 1


def _find_next_open_brace(content: str, start: int) -> Optional[int]:
    idx = start
    while idx < len(content) and content[idx].isspace():
        idx += 1
    if idx < len(content) and content[idx] == "{":
        return idx
    return None


def _find_matching_brace(content: str, open_brace_idx: int) -> Optional[int]:
    """Find matching closing brace while ignoring comments/strings."""
    depth = 0
    idx = open_brace_idx

    in_line_comment = False
    in_block_comment = False
    in_single_quote = False
    in_double_quote = False
    in_verbatim_string = False

    while idx < len(content):
        ch = content[idx]
        nxt = content[idx + 1] if idx + 1 < len(content) else ""
        nxt2 = content[idx + 2] if idx + 2 < len(content) else ""

        if in_line_comment:
            if ch == "\n":
                in_line_comment = False
        elif in_block_comment:
            if ch == "*" and nxt == "/":
                in_block_comment = False
                idx += 1
        elif in_single_quote:
            if ch == "\\" and nxt:
                idx += 1
            elif ch == "'":
                in_single_quote = False
        elif in_double_quote:
            if in_verbatim_string:
                if ch == '"' and nxt == '"':
                    idx += 1
                elif ch == '"':
                    in_double_quote = False
                    in_verbatim_string = False
            else:
                if ch == "\\" and nxt:
                    idx += 1
                elif ch == '"':
                    in_double_quote = False
        else:
            if ch == "/" and nxt == "/":
                in_line_comment = True
                idx += 1
            elif ch == "/" and nxt == "*":
                in_block_comment = True
                idx += 1
            elif ch == "$" and nxt == "@" and nxt2 == '"':
                in_double_quote = True
                in_verbatim_string = True
                idx += 2
            elif ch == "@" and nxt == "$" and nxt2 == '"':
                in_double_quote = True
                in_verbatim_string = True
                idx += 2
            elif ch == "@" and nxt == '"':
                in_double_quote = True
                in_verbatim_string = True
                idx += 1
            elif ch == "$" and nxt == '"':
                in_double_quote = True
                in_verbatim_string = False
                idx += 1
            elif ch == '"':
                in_double_quote = True
                in_verbatim_string = False
            elif ch == "'":
                in_single_quote = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return idx

        idx += 1

    return None


def _walk_tree(
    node,
    spec: LanguageSpec,
    source_bytes: bytes,
    filename: str,
    language: str,
    symbols: list[Symbol],
    parent_symbol: Optional[Symbol] = None,
):
    """Recursively walk the AST and extract symbols."""
    if node.type in spec.symbol_node_types:
        symbol = _extract_symbol(
            node,
            spec,
            source_bytes,
            filename,
            language,
            parent_symbol,
        )
        if symbol:
            symbols.append(symbol)
            parent_symbol = symbol

    if node.type in spec.constant_patterns:
        const_symbol = _extract_constant(
            node=node,
            spec=spec,
            source_bytes=source_bytes,
            filename=filename,
            language=language,
            parent_symbol=parent_symbol,
        )
        if const_symbol:
            symbols.append(const_symbol)

    for child in node.children:
        _walk_tree(child, spec, source_bytes, filename, language, symbols, parent_symbol)


def _extract_symbol(
    node,
    spec: LanguageSpec,
    source_bytes: bytes,
    filename: str,
    language: str,
    parent_symbol: Optional[Symbol] = None,
) -> Optional[Symbol]:
    """Extract a Symbol from an AST node."""
    kind = spec.symbol_node_types[node.type]

    if node.has_error:
        return None

    name = _extract_name(node, spec, source_bytes)
    if not name:
        return None

    if parent_symbol:
        qualified_name = f"{parent_symbol.name}.{name}"
        kind = "method" if kind == "function" else kind
    else:
        qualified_name = name

    signature = _build_signature(node, source_bytes)
    docstring = _extract_docstring(node, spec, source_bytes)
    decorators = _extract_decorators(node, spec, source_bytes)

    symbol_bytes = source_bytes[node.start_byte : node.end_byte]
    c_hash = compute_content_hash(symbol_bytes)

    return Symbol(
        id=make_symbol_id(filename, qualified_name, kind),
        file=filename,
        name=name,
        qualified_name=qualified_name,
        kind=kind,
        language=language,
        signature=signature,
        docstring=docstring,
        decorators=decorators,
        parent=parent_symbol.id if parent_symbol else None,
        line=node.start_point[0] + 1,
        end_line=node.end_point[0] + 1,
        byte_offset=node.start_byte,
        byte_length=node.end_byte - node.start_byte,
        content_hash=c_hash,
    )


def _extract_name(node, spec: LanguageSpec, source_bytes: bytes) -> Optional[str]:
    """Extract the name from an AST node."""
    if node.type == "arrow_function":
        return None

    if node.type == "type_declaration":
        for child in node.children:
            if child.type == "type_spec":
                name_node = child.child_by_field_name("name")
                if name_node:
                    return source_bytes[name_node.start_byte : name_node.end_byte].decode(
                        "utf-8"
                    )
        return None

    if node.type not in spec.name_fields:
        return None

    field_name = spec.name_fields[node.type]
    name_node = node.child_by_field_name(field_name)
    if name_node:
        return source_bytes[name_node.start_byte : name_node.end_byte].decode("utf-8")
    return None


def _build_signature(node, source_bytes: bytes) -> str:
    """Build a clean signature from AST node."""
    body = node.child_by_field_name("body")
    if body:
        end_byte = body.start_byte
    else:
        end_byte = node.end_byte

    sig_bytes = source_bytes[node.start_byte:end_byte]
    sig_text = sig_bytes.decode("utf-8").strip().rstrip("{: \n\t")

    # For block constructs without a body field, keep only declaration header line.
    if "\n" in sig_text and body is None:
        sig_text = sig_text.splitlines()[0].strip()

    return sig_text


def _extract_docstring(node, spec: LanguageSpec, source_bytes: bytes) -> str:
    """Extract docstring using language-specific strategy."""
    if spec.docstring_strategy == "next_sibling_string":
        return _extract_python_docstring(node, source_bytes)
    if spec.docstring_strategy == "preceding_comment":
        return _extract_preceding_comments(node, source_bytes)
    return ""


def _extract_python_docstring(node, source_bytes: bytes) -> str:
    """Extract Python docstring from first statement in body."""
    body = node.child_by_field_name("body")
    if not body or body.child_count == 0:
        return ""

    for child in body.children:
        if child.type == "expression_statement":
            expr = child.child_by_field_name("expression")
            if expr and expr.type == "string":
                doc = source_bytes[expr.start_byte : expr.end_byte].decode("utf-8")
                return _strip_quotes(doc)
            if child.child_count > 0:
                first = child.children[0]
                if first.type in ("string", "concatenated_string"):
                    doc = source_bytes[first.start_byte : first.end_byte].decode("utf-8")
                    return _strip_quotes(doc)
        elif child.type == "string":
            doc = source_bytes[child.start_byte : child.end_byte].decode("utf-8")
            return _strip_quotes(doc)

    return ""


def _strip_quotes(text: str) -> str:
    """Strip quotes from a docstring."""
    text = text.strip()
    if text.startswith('"""') and text.endswith('"""'):
        return text[3:-3].strip()
    if text.startswith("'''") and text.endswith("'''"):
        return text[3:-3].strip()
    if text.startswith('"') and text.endswith('"'):
        return text[1:-1].strip()
    if text.startswith("'") and text.endswith("'"):
        return text[1:-1].strip()
    return text


def _extract_preceding_comments(node, source_bytes: bytes) -> str:
    """Extract comments that immediately precede a node."""
    comments = []

    prev = node.prev_named_sibling
    while prev and prev.type in ("comment", "line_comment", "block_comment"):
        comment_text = source_bytes[prev.start_byte : prev.end_byte].decode("utf-8")
        comments.insert(0, comment_text)
        prev = prev.prev_named_sibling

    if not comments:
        return ""

    docstring = "\n".join(comments)
    return _clean_comment_markers(docstring)


def _clean_comment_markers(text: str) -> str:
    """Clean comment markers from docstring."""
    lines = text.split("\n")
    cleaned = []

    for line in lines:
        line = line.strip()
        if line.startswith("/**"):
            line = line[3:]
        elif line.startswith("/*"):
            line = line[2:]
        elif line.startswith("///"):
            line = line[3:]
        elif line.startswith("//"):
            line = line[2:]
        elif line.startswith("//!"):
            line = line[3:]
        elif line.startswith("'"):
            line = line[1:]
        elif line.startswith("*"):
            line = line[1:]

        if line.endswith("*/"):
            line = line[:-2]

        cleaned.append(line.strip())

    return "\n".join(cleaned).strip()


def _extract_decorators(node, spec: LanguageSpec, source_bytes: bytes) -> list[str]:
    """Extract decorators/attributes from a node."""
    if not spec.decorator_node_type:
        return []

    decorators = []

    for child in node.children:
        if child.type == spec.decorator_node_type:
            text = source_bytes[child.start_byte : child.end_byte].decode("utf-8").strip()
            if text:
                decorators.append(text)

    prev = node.prev_named_sibling
    while prev and prev.type == spec.decorator_node_type:
        text = source_bytes[prev.start_byte : prev.end_byte].decode("utf-8").strip()
        if text:
            decorators.insert(0, text)
        prev = prev.prev_named_sibling

    # Deduplicate while preserving order.
    seen: set[str] = set()
    unique: list[str] = []
    for item in decorators:
        if item not in seen:
            seen.add(item)
            unique.append(item)
    return unique


def _extract_constant(
    node,
    spec: LanguageSpec,
    source_bytes: bytes,
    filename: str,
    language: str,
    parent_symbol: Optional[Symbol] = None,
) -> Optional[Symbol]:
    """Extract constants for supported declaration styles."""
    name: Optional[str] = None

    if node.type == "assignment":
        if language != "python" or parent_symbol is not None:
            return None
        left = node.child_by_field_name("left")
        if left and left.type == "identifier":
            candidate = source_bytes[left.start_byte : left.end_byte].decode("utf-8")
            if candidate.isupper() or (
                len(candidate) > 1 and candidate[0].isupper() and "_" in candidate
            ):
                name = candidate

    elif node.type == "const_declaration":
        if node.type not in spec.name_fields:
            return None
        field_name = spec.name_fields[node.type]
        name_node = node.child_by_field_name(field_name)
        if name_node:
            name = source_bytes[name_node.start_byte : name_node.end_byte].decode("utf-8")

    elif node.type == "field_declaration":
        if language == "csharp":
            if not _node_has_modifier(node, "const", source_bytes):
                return None
        elif language == "java":
            if not (
                _node_has_modifier(node, "static", source_bytes)
                and _node_has_modifier(node, "final", source_bytes)
            ):
                return None
        else:
            return None

        name = _extract_first_variable_name(node, source_bytes)

    if not name:
        return None

    if parent_symbol:
        qualified_name = f"{parent_symbol.name}.{name}"
        parent_id = parent_symbol.id
    else:
        qualified_name = name
        parent_id = None

    signature = source_bytes[node.start_byte : node.end_byte].decode("utf-8").strip()
    const_bytes = source_bytes[node.start_byte : node.end_byte]
    content_hash = compute_content_hash(const_bytes)

    return Symbol(
        id=make_symbol_id(filename, qualified_name, "constant"),
        file=filename,
        name=name,
        qualified_name=qualified_name,
        kind="constant",
        language=language,
        signature=signature[:160],
        parent=parent_id,
        line=node.start_point[0] + 1,
        end_line=node.end_point[0] + 1,
        byte_offset=node.start_byte,
        byte_length=node.end_byte - node.start_byte,
        content_hash=content_hash,
    )


def _node_has_modifier(node, modifier: str, source_bytes: bytes) -> bool:
    lower_modifier = modifier.lower()
    for child in node.children:
        if child.type != "modifier":
            continue
        text = source_bytes[child.start_byte : child.end_byte].decode("utf-8").strip().lower()
        if text == lower_modifier:
            return True
    return False


def _extract_first_variable_name(node, source_bytes: bytes) -> Optional[str]:
    for child in node.children:
        if child.type != "variable_declaration":
            continue
        for grand in child.children:
            if grand.type != "variable_declarator":
                continue
            name_node = grand.child_by_field_name("name")
            if name_node:
                return source_bytes[name_node.start_byte : name_node.end_byte].decode(
                    "utf-8"
                )
    return None


def _disambiguate_overloads(symbols: list[Symbol]) -> list[Symbol]:
    """Append ordinal suffix to symbols with duplicate IDs."""
    from collections import Counter

    id_counts = Counter(s.id for s in symbols)
    duplicated = {sid for sid, count in id_counts.items() if count > 1}

    if not duplicated:
        return symbols

    ordinals: dict[str, int] = {}
    result = []
    for sym in symbols:
        if sym.id in duplicated:
            ordinals[sym.id] = ordinals.get(sym.id, 0) + 1
            sym.id = f"{sym.id}~{ordinals[sym.id]}"
        result.append(sym)
    return result
