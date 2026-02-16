# Symbol Specification

## Symbol ID Format

```
{file_path}::{qualified_name}#{kind}
```

**Examples:**

* `src/main.py::MyClass#class`
* `src/main.py::MyClass.method#method`
* `src/main.py::standalone#function`
* `src/main.py::MAX_SIZE#constant`

### Components

| Part             | Description                                                     |
| ---------------- | --------------------------------------------------------------- |
| `file_path`      | Relative file path within the repository (e.g., `src/main.py`)  |
| `qualified_name` | Dot-separated name with parent context (e.g., `MyClass.method`) |
| `kind`           | Symbol kind: `function`, `class`, `method`, `constant`, `type`  |

### Overload Disambiguation

When multiple symbols produce the same ID (for example, overloaded methods in Java or TypeScript), an ordinal suffix `~N` is appended:

* `MyClass.method#method~1`
* `MyClass.method#method~2`

### ID Stability Rules

* **Stable across re-index** if file path, qualified name, and kind are unchanged.
* **Changes on:** file rename, symbol rename, or kind change.
* **Decorators do not affect IDs.** Decorators are stored separately as metadata.

---

## Symbol Kinds

| Kind       | Description                                          |
| ---------- | ---------------------------------------------------- |
| `function` | Top-level function or free-standing function         |
| `class`    | Class definition (or `impl` block in Rust)           |
| `method`   | Function nested inside a class, trait, or impl block |
| `constant` | Uppercase top-level assignment or const declaration  |
| `type`     | Interface, type alias, enum, struct, or trait        |

---

## Content Hash

Each symbol stores a `content_hash`: SHA-256 of the raw source bytes.

* Used for **drift detection** to verify the source has not changed since indexing.
* **Not part of the symbol ID** — IDs are structural, not content-based.
* Can be verified via `get_symbol(repo, id, verify=True)`, which returns `_meta.content_verified`.

---

## Per-Language Symbol Extraction

### Python

* **Symbols:** `function_definition` → function, `class_definition` → class
* **Qualified names:** `ClassName.method_name` for methods
* **Containers:** `class_definition` (methods inside classes)
* **Constants:** `assignment` nodes where the left side is an uppercase identifier
* **Decorators:** `decorator` nodes before function/class definitions
* **Docstrings:** First string expression inside the body (triple-quoted)

### JavaScript

* **Symbols:** `function_declaration`, `class_declaration`, `method_definition`, `generator_function_declaration`
* **Containers:** `class_declaration`
* **Constants:** `lexical_declaration` (`const` with uppercase name)
* **Docstrings:** Preceding `//` or `/** */` comments
* **Note:** Anonymous arrow functions are not indexed (no stable name)

### TypeScript

* **Symbols:** Same as JavaScript plus `interface_declaration`, `type_alias_declaration`, `enum_declaration`
* **Decorators:** `decorator` nodes
* **Types:** Interfaces, type aliases, and enums extracted as `type` kind

### Go

* **Symbols:** `function_declaration`, `method_declaration`, `type_declaration`
* **Containers:** None (Go has no class-style nesting)
* **Constants:** `const_declaration`
* **Types:** `type_declaration` (structs, interfaces via `type_spec`)
* **Docstrings:** Preceding `//` comments

### Rust

* **Symbols:** `function_item`, `struct_item`, `enum_item`, `trait_item`, `impl_item`, `type_item`
* **Containers:** `impl_item`, `trait_item` (methods inside impl/trait blocks)
* **Constants:** `const_item`, `static_item`
* **Decorators:** `attribute_item` (e.g., `#[derive(Debug)]`)
* **Docstrings:** Preceding `///` or `//!` comments

### Java

* **Symbols:** `method_declaration`, `constructor_declaration`, `class_declaration`, `interface_declaration`, `enum_declaration`
* **Containers:** `class_declaration`, `interface_declaration`, `enum_declaration`
* **Constants:** `field_declaration` (uppercase identifiers)
* **Decorators:** `marker_annotation` (e.g., `@Override`)
* **Docstrings:** Preceding `/** */` Javadoc comments

---

## Known Limitations

* **Anonymous functions:** Arrow functions without stable names are skipped.
* **Deeply nested scopes:** Parent tracking is limited (e.g., `Class.method`, not `Module.Class.InnerClass.method`).
* **Generated code:** Often excluded via default skip patterns (`generated/`, `proto/`, etc.).
* **Macro-generated symbols:** Not visible to tree-sitter AST parsing.
* **Conditional compilation:** All branches are parsed regardless of compile-time conditions.
