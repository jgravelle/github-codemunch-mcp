# Language Support

## Supported Languages

| Language | Extensions | Parser | Symbol Types | Decorators | Docstrings | Known Limitations |
|----------|-----------|--------|-------------|-----------|-----------|-------------------|
| Python | `.py` | tree-sitter-python | function, class, method, constant, type | `@decorator` | Triple-quoted strings | Type alias requires Python 3.12+ syntax |
| JavaScript | `.js`, `.jsx` | tree-sitter-javascript | function, class, method, constant | None | `//` / `/** */` comments | Arrow functions without names skipped |
| TypeScript | `.ts`, `.tsx` | tree-sitter-typescript | function, class, method, constant, type | `@decorator` | `//` / `/** */` comments | Decorators require TC39 stage 3+ |
| Go | `.go` | tree-sitter-go | function, method, type, constant | None | `//` comments | No class-like nesting |
| Rust | `.rs` | tree-sitter-rust | function, type (struct/enum/trait), class (impl), constant | `#[attr]` | `///` / `//!` comments | Macro-generated items invisible |
| Java | `.java` | tree-sitter-java | method, class, type (interface/enum), constant | `@Annotation` | `/** */` Javadoc | Inner classes have limited nesting |

## Parser: tree-sitter

All parsing uses [tree-sitter](https://tree-sitter.github.io/) via the `tree-sitter-language-pack` Python package. This provides:

- Incremental, error-tolerant parsing
- Consistent AST representation across languages
- Pre-compiled bindings for all 6 languages

**Dependency:** `tree-sitter-language-pack>=0.7.0` (pinned in `pyproject.toml`)

## Adding a New Language

1. **Create a `LanguageSpec`** in `src/jcodemunch_mcp/parser/languages.py`:

```python
NEW_LANG_SPEC = LanguageSpec(
    ts_language="new_language",           # tree-sitter grammar name
    symbol_node_types={                    # AST node type -> symbol kind
        "function_definition": "function",
        "class_definition": "class",
    },
    name_fields={                          # How to extract names
        "function_definition": "name",
        "class_definition": "name",
    },
    param_fields={                         # Parameter extraction
        "function_definition": "parameters",
    },
    return_type_fields={},                 # Return type extraction
    docstring_strategy="preceding_comment", # or "next_sibling_string"
    decorator_node_type=None,              # Decorator node type if any
    container_node_types=["class_definition"],  # Nesting containers
    constant_patterns=[],                  # Constant node types
    type_patterns=[],                      # Type definition node types
)
```

2. **Register it** in `LANGUAGE_REGISTRY`:
```python
LANGUAGE_REGISTRY["new_language"] = NEW_LANG_SPEC
```

3. **Add file extensions** to `LANGUAGE_EXTENSIONS`:
```python
LANGUAGE_EXTENSIONS[".ext"] = "new_language"
```

4. **Verify** the tree-sitter grammar name exists in `tree-sitter-language-pack`:
```python
from tree_sitter_language_pack import get_parser
parser = get_parser("new_language")  # Must not raise
```

5. **Write tests** in `tests/test_parser.py`:
```python
def test_parse_new_language():
    source = "..."  # Minimal source with function + class
    symbols = parse_file(source, "test.ext", "new_language")
    assert len(symbols) >= 2
```

## Debugging AST Node Types

To inspect what tree-sitter produces for a given source file:

```python
from tree_sitter_language_pack import get_parser

parser = get_parser("python")
tree = parser.parse(b"def foo(): pass")

def print_tree(node, indent=0):
    print(" " * indent + f"{node.type} [{node.start_point}-{node.end_point}]")
    for child in node.children:
        print_tree(child, indent + 2)

print_tree(tree.root_node)
```

This helps identify the correct `symbol_node_types` and `name_fields` for a new language.
