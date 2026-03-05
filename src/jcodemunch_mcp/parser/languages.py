"""Language registry with LanguageSpec definitions for all supported languages."""

from dataclasses import dataclass
from typing import Optional


@dataclass
class LanguageSpec:
    """Specification for extracting symbols from a language's AST."""
    # tree-sitter language name (for tree-sitter-language-pack)
    ts_language: str

    # Node types that represent extractable symbols
    # Maps node_type -> symbol kind
    symbol_node_types: dict[str, str]

    # How to extract the symbol name from a node
    # Maps node_type -> child field name containing the name
    name_fields: dict[str, str]

    # How to extract parameters/signature beyond the name
    # Maps node_type -> child field name for parameters
    param_fields: dict[str, str]

    # Return type extraction (if language supports it)
    # Maps node_type -> child field name for return type
    return_type_fields: dict[str, str]

    # Docstring extraction strategy
    # "next_sibling_string" = Python (expression_statement after def)
    # "first_child_comment" = JS/TS (/** */ before function)
    # "preceding_comment" = Go/Rust/Java (// or /* */ before decl)
    docstring_strategy: str

    # Decorator/attribute node type (if any)
    decorator_node_type: Optional[str]

    # Node types that indicate nesting (methods inside classes)
    container_node_types: list[str]

    # Additional extraction: constants, type aliases
    constant_patterns: list[str]   # Node types for constants
    type_patterns: list[str]       # Node types for type definitions

    # If True, decorators are direct children of the declaration node (e.g. C#)
    # If False (default), decorators are preceding siblings (e.g. Python, Java)
    decorator_from_children: bool = False


# File extension to language mapping
LANGUAGE_EXTENSIONS = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".php": "php",
    ".dart": "dart",
    ".cs": "csharp",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".hpp": "cpp",
    ".cc": "cpp",
    ".hh": "cpp",
    ".cxx": "cpp",
    ".hxx": "cpp",
    ".swift": "swift",
}


# Python specification
PYTHON_SPEC = LanguageSpec(
    ts_language="python",
    symbol_node_types={
        "function_definition": "function",
        "class_definition": "class",
    },
    name_fields={
        "function_definition": "name",
        "class_definition": "name",
    },
    param_fields={
        "function_definition": "parameters",
    },
    return_type_fields={
        "function_definition": "return_type",
    },
    docstring_strategy="next_sibling_string",
    decorator_node_type="decorator",
    container_node_types=["class_definition"],
    constant_patterns=["assignment"],
    type_patterns=["type_alias_statement"],
)


# JavaScript specification
JAVASCRIPT_SPEC = LanguageSpec(
    ts_language="javascript",
    symbol_node_types={
        "function_declaration": "function",
        "class_declaration": "class",
        "method_definition": "method",
        "arrow_function": "function",
        "generator_function_declaration": "function",
    },
    name_fields={
        "function_declaration": "name",
        "class_declaration": "name",
        "method_definition": "name",
    },
    param_fields={
        "function_declaration": "parameters",
        "method_definition": "parameters",
        "arrow_function": "parameters",
    },
    return_type_fields={},
    docstring_strategy="preceding_comment",
    decorator_node_type=None,
    container_node_types=["class_declaration", "class"],
    constant_patterns=["lexical_declaration"],
    type_patterns=[],
)


# TypeScript specification
TYPESCRIPT_SPEC = LanguageSpec(
    ts_language="typescript",
    symbol_node_types={
        "function_declaration": "function",
        "class_declaration": "class",
        "method_definition": "method",
        "arrow_function": "function",
        "interface_declaration": "type",
        "type_alias_declaration": "type",
        "enum_declaration": "type",
    },
    name_fields={
        "function_declaration": "name",
        "class_declaration": "name",
        "method_definition": "name",
        "interface_declaration": "name",
        "type_alias_declaration": "name",
        "enum_declaration": "name",
    },
    param_fields={
        "function_declaration": "parameters",
        "method_definition": "parameters",
        "arrow_function": "parameters",
    },
    return_type_fields={
        "function_declaration": "return_type",
        "method_definition": "return_type",
        "arrow_function": "return_type",
    },
    docstring_strategy="preceding_comment",
    decorator_node_type="decorator",
    container_node_types=["class_declaration", "class"],
    constant_patterns=["lexical_declaration"],
    type_patterns=["interface_declaration", "type_alias_declaration", "enum_declaration"],
)


# Go specification
GO_SPEC = LanguageSpec(
    ts_language="go",
    symbol_node_types={
        "function_declaration": "function",
        "method_declaration": "method",
        "type_declaration": "type",
    },
    name_fields={
        "function_declaration": "name",
        "method_declaration": "name",
        "type_declaration": "name",
    },
    param_fields={
        "function_declaration": "parameters",
        "method_declaration": "parameters",
    },
    return_type_fields={
        "function_declaration": "result",
        "method_declaration": "result",
    },
    docstring_strategy="preceding_comment",
    decorator_node_type=None,
    container_node_types=[],
    constant_patterns=["const_declaration"],
    type_patterns=["type_declaration"],
)


# Rust specification
RUST_SPEC = LanguageSpec(
    ts_language="rust",
    symbol_node_types={
        "function_item": "function",
        "struct_item": "type",
        "enum_item": "type",
        "trait_item": "type",
        "impl_item": "class",
        "type_item": "type",
    },
    name_fields={
        "function_item": "name",
        "struct_item": "name",
        "enum_item": "name",
        "trait_item": "name",
        "type_item": "name",
    },
    param_fields={
        "function_item": "parameters",
    },
    return_type_fields={
        "function_item": "return_type",
    },
    docstring_strategy="preceding_comment",
    decorator_node_type="attribute_item",
    container_node_types=["impl_item", "trait_item"],
    constant_patterns=["const_item", "static_item"],
    type_patterns=["struct_item", "enum_item", "trait_item", "type_item"],
)


# Java specification
JAVA_SPEC = LanguageSpec(
    ts_language="java",
    symbol_node_types={
        "method_declaration": "method",
        "constructor_declaration": "method",
        "class_declaration": "class",
        "interface_declaration": "type",
        "enum_declaration": "type",
    },
    name_fields={
        "method_declaration": "name",
        "constructor_declaration": "name",
        "class_declaration": "name",
        "interface_declaration": "name",
        "enum_declaration": "name",
    },
    param_fields={
        "method_declaration": "parameters",
        "constructor_declaration": "parameters",
    },
    return_type_fields={
        "method_declaration": "type",
    },
    docstring_strategy="preceding_comment",
    decorator_node_type="marker_annotation",
    container_node_types=["class_declaration", "interface_declaration", "enum_declaration"],
    constant_patterns=["field_declaration"],
    type_patterns=["interface_declaration", "enum_declaration"],
)


# PHP specification
PHP_SPEC = LanguageSpec(
    ts_language="php",
    symbol_node_types={
        "function_definition": "function",
        "class_declaration": "class",
        "method_declaration": "method",
        "interface_declaration": "type",
        "trait_declaration": "type",
        "enum_declaration": "type",
    },
    name_fields={
        "function_definition": "name",
        "class_declaration": "name",
        "method_declaration": "name",
        "interface_declaration": "name",
        "trait_declaration": "name",
        "enum_declaration": "name",
    },
    param_fields={
        "function_definition": "parameters",
        "method_declaration": "parameters",
    },
    return_type_fields={
        "function_definition": "return_type",
        "method_declaration": "return_type",
    },
    docstring_strategy="preceding_comment",
    decorator_node_type="attribute",  # PHP 8 #[Attribute] syntax
    container_node_types=["class_declaration", "trait_declaration", "interface_declaration"],
    constant_patterns=["const_declaration"],
    type_patterns=["interface_declaration", "trait_declaration", "enum_declaration"],
)


# Dart specification
DART_SPEC = LanguageSpec(
    ts_language="dart",
    symbol_node_types={
        "function_signature": "function",
        "class_definition": "class",
        "mixin_declaration": "class",
        "enum_declaration": "type",
        "extension_declaration": "class",
        "method_signature": "method",
        "type_alias": "type",
    },
    name_fields={
        "function_signature": "name",
        "class_definition": "name",
        "enum_declaration": "name",
        "extension_declaration": "name",
        # mixin_declaration, method_signature, type_alias: special-cased in extractor
    },
    param_fields={
        "function_signature": "parameters",
    },
    return_type_fields={},
    docstring_strategy="preceding_comment",
    decorator_node_type="annotation",
    container_node_types=["class_definition", "mixin_declaration", "extension_declaration"],
    constant_patterns=[],
    type_patterns=["type_alias", "enum_declaration"],
)


# C# specification
CSHARP_SPEC = LanguageSpec(
    ts_language="csharp",
    symbol_node_types={
        "class_declaration": "class",
        "record_declaration": "class",
        "interface_declaration": "type",
        "enum_declaration": "type",
        "struct_declaration": "type",
        "delegate_declaration": "type",
        "method_declaration": "method",
        "constructor_declaration": "method",
    },
    name_fields={
        "class_declaration": "name",
        "record_declaration": "name",
        "interface_declaration": "name",
        "enum_declaration": "name",
        "struct_declaration": "name",
        "delegate_declaration": "name",
        "method_declaration": "name",
        "constructor_declaration": "name",
    },
    param_fields={
        "method_declaration": "parameters",
        "constructor_declaration": "parameters",
        "delegate_declaration": "parameters",
    },
    return_type_fields={
        "method_declaration": "returns",
    },
    docstring_strategy="preceding_comment",
    decorator_node_type="attribute_list",
    decorator_from_children=True,
    container_node_types=["class_declaration", "struct_declaration", "record_declaration", "interface_declaration"],
    constant_patterns=[],
    type_patterns=["interface_declaration", "enum_declaration", "struct_declaration", "delegate_declaration", "record_declaration"],
)


# C specification
C_SPEC = LanguageSpec(
    ts_language="c",
    symbol_node_types={
        "function_definition": "function",
        "struct_specifier": "type",
        "enum_specifier": "type",
        "union_specifier": "type",
        "type_definition": "type",
    },
    name_fields={
        "function_definition": "declarator",
        "struct_specifier": "name",
        "enum_specifier": "name",
        "union_specifier": "name",
        "type_definition": "declarator",
    },
    param_fields={
        "function_definition": "declarator",
    },
    return_type_fields={
        "function_definition": "type",
    },
    docstring_strategy="preceding_comment",
    decorator_node_type=None,
    container_node_types=[],
    constant_patterns=["preproc_def"],
    type_patterns=["type_definition", "enum_specifier", "struct_specifier", "union_specifier"],
)


# C++ specification
CPP_SPEC = LanguageSpec(
    ts_language="cpp",
    symbol_node_types={
        "function_definition": "function",
        "class_specifier": "class",
        "struct_specifier": "type",
        "enum_specifier": "type",
        "union_specifier": "type",
        "type_definition": "type",
    },
    name_fields={
        "function_definition": "declarator",
        "class_specifier": "name",
        "struct_specifier": "name",
        "enum_specifier": "name",
        "union_specifier": "name",
        "type_definition": "declarator",
    },
    param_fields={
        "function_definition": "declarator",
    },
    return_type_fields={
        "function_definition": "type",
    },
    docstring_strategy="preceding_comment",
    decorator_node_type=None,
    container_node_types=["class_specifier", "struct_specifier"],
    constant_patterns=["preproc_def"],
    type_patterns=["type_definition", "enum_specifier", "struct_specifier", "union_specifier"],
)


# Swift specification
# Note: tree-sitter-swift uses class_declaration for class/struct/enum/extension;
# the declaration_kind child field ("class"/"struct"/"enum"/"extension") disambiguates
# at the source level but all map to "class" here for uniform treatment.
# Attributes (@discardableResult etc.) live inside a modifiers child node rather
# than as preceding siblings, so decorator extraction is not supported in this spec.
SWIFT_SPEC = LanguageSpec(
    ts_language="swift",
    symbol_node_types={
        "function_declaration": "function",
        "class_declaration": "class",    # covers class, struct, enum, extension
        "protocol_declaration": "type",
        "init_declaration": "method",
    },
    name_fields={
        "function_declaration": "name",  # simple_identifier child
        "class_declaration": "name",     # type_identifier child
        "protocol_declaration": "name",  # type_identifier child
        "init_declaration": "name",      # "init" keyword token
    },
    param_fields={},  # Swift params are unnamed children; signature captured via source range
    return_type_fields={},  # return type shares field "name" with function identifier
    docstring_strategy="preceding_comment",  # /// and /* */ doc comments
    decorator_node_type=None,
    container_node_types=["class_declaration", "protocol_declaration"],
    constant_patterns=["property_declaration"],  # let/var at file scope
    type_patterns=["protocol_declaration"],
)


# Language registry
LANGUAGE_REGISTRY = {
    "python": PYTHON_SPEC,
    "javascript": JAVASCRIPT_SPEC,
    "typescript": TYPESCRIPT_SPEC,
    "go": GO_SPEC,
    "rust": RUST_SPEC,
    "java": JAVA_SPEC,
    "php": PHP_SPEC,
    "dart": DART_SPEC,
    "csharp": CSHARP_SPEC,
    "c": C_SPEC,
    "cpp": CPP_SPEC,
    "swift": SWIFT_SPEC,
}
