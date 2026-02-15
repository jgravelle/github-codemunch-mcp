# Symbol Specification

## Symbol ID Format

```
{file_path}::{qualified_name}#{kind}
```

**Examples:**
- `src/main.py::MyClass#class`
- `src/main.py::MyClass.method#method`
- `src/main.py::standalone#function`
- `src/main.py::MAX_SIZE#constant`

### Components

| Part | Description |
|------|-------------|
| `file_path` | Relative file path within the repo (e.g., `src/main.py`) |
| `qualified_name` | Dot-separated name with parent context (e.g., `MyClass.method`) |
| `kind` | Symbol kind: `function`, `class`, `method`, `constant`, `type` |

### Overload Disambiguation

When multiple symbols produce the same ID (e.g., overloaded methods in Java/TypeScript), an ordinal suffix `~N` is appended:
- `MyClass.method#method~1`
- `MyClass.method#method~2`

### ID Stability Rules

- **Stable across re-index** if file path, qualified name, and kind are unchanged.
- **Changes on:** file rename, symbol rename, kind change.
- **Decorators do NOT affect IDs.** Decorators are metadata stored separately.

## Symbol Kinds

| Kind | Description |
|------|-------------|
| `function` | Top-level function or free-standing function |
| `class` | Class definition (or impl block in Rust) |
| `method` | Function nested inside a class/impl/trait |
| `constant` | UPPER_CASE top-level assignment or const declaration |
| `type` | Interface, type alias, enum, struct, trait |

## Content Hash

Each symbol stores a `content_hash`: SHA-256 of the raw source bytes.

- Used for **drift detection**: verify that the source hasn't changed since indexing.
- **Not part of the symbol ID** — IDs are based on structure, not content.
- Can be verified via `get_symbol(repo, id, verify=True)` which returns `_meta.content_verified`.

## Per-Language Symbol Extraction

### Python
- **Symbols:** `function_definition` -> function, `class_definition` -> class
- **Qualified names:** `ClassName.method_name` for methods
- **Containers:** `class_definition` (methods inside classes)
- **Constants:** `assignment` nodes where left side is UPPER_CASE identifier
- **Decorators:** `decorator` nodes before function/class definitions
- **Docstrings:** First expression_statement string in body (triple-quoted)

### JavaScript
- **Symbols:** `function_declaration`, `class_declaration`, `method_definition`, `arrow_function`, `generator_function_declaration`
- **Containers:** `class_declaration`, `class`
- **Constants:** `lexical_declaration` (const with UPPER_CASE name)
- **Docstrings:** Preceding `//` or `/** */` comments

### TypeScript
- **Symbols:** Same as JavaScript plus `interface_declaration`, `type_alias_declaration`, `enum_declaration`
- **Decorators:** `decorator` nodes
- **Types:** Interfaces, type aliases, enums extracted as `type` kind

### Go
- **Symbols:** `function_declaration`, `method_declaration`, `type_declaration`
- **Containers:** None (Go doesn't have class-like nesting)
- **Constants:** `const_declaration`
- **Types:** `type_declaration` (structs, interfaces via type_spec)
- **Docstrings:** Preceding `//` comments

### Rust
- **Symbols:** `function_item`, `struct_item`, `enum_item`, `trait_item`, `impl_item`, `type_item`
- **Containers:** `impl_item`, `trait_item` (methods inside impl/trait blocks)
- **Constants:** `const_item`, `static_item`
- **Decorators:** `attribute_item` (e.g., `#[derive(Debug)]`)
- **Docstrings:** Preceding `///` or `//!` comments

### Java
- **Symbols:** `method_declaration`, `constructor_declaration`, `class_declaration`, `interface_declaration`, `enum_declaration`
- **Containers:** `class_declaration`, `interface_declaration`, `enum_declaration`
- **Constants:** `field_declaration` (with UPPER_CASE name)
- **Decorators:** `marker_annotation` (e.g., `@Override`)
- **Docstrings:** Preceding `/** */` Javadoc comments

## Known Limitations

- **Anonymous functions:** Arrow functions without a name are skipped (no name to extract).
- **Deeply nested scopes:** Only one level of parent tracking (e.g., `Class.method` but not `Module.Class.InnerClass.method`).
- **Generated code:** Excluded by default via SKIP_PATTERNS (`generated/`, `proto/`).
- **Macro-generated symbols:** Not visible to tree-sitter AST parsing.
- **Conditional compilation:** All branches are parsed regardless of conditions.
