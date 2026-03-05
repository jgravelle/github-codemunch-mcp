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
    ".cs": "csharp",
    ".csx": "csharp",
    ".razor": "csharp",
    ".cshtml": "csharp",
    ".vb": "vb",
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


# C# specification
CSHARP_SPEC = LanguageSpec(
    ts_language="csharp",
    symbol_node_types={
        "class_declaration": "class",
        "struct_declaration": "type",
        "interface_declaration": "type",
        "enum_declaration": "type",
        "record_declaration": "type",
        "delegate_declaration": "type",
        "method_declaration": "method",
        "constructor_declaration": "method",
        "property_declaration": "method",
    },
    name_fields={
        "class_declaration": "name",
        "struct_declaration": "name",
        "interface_declaration": "name",
        "enum_declaration": "name",
        "record_declaration": "name",
        "delegate_declaration": "name",
        "method_declaration": "name",
        "constructor_declaration": "name",
        "property_declaration": "name",
    },
    param_fields={
        "method_declaration": "parameters",
        "constructor_declaration": "parameters",
    },
    return_type_fields={
        "method_declaration": "returns",
        "delegate_declaration": "type",
        "property_declaration": "type",
    },
    docstring_strategy="preceding_comment",
    decorator_node_type="attribute_list",
    container_node_types=[
        "class_declaration",
        "struct_declaration",
        "interface_declaration",
        "record_declaration",
    ],
    constant_patterns=["field_declaration"],
    type_patterns=[
        "struct_declaration",
        "interface_declaration",
        "enum_declaration",
        "record_declaration",
        "delegate_declaration",
    ],
)


# Visual Basic .NET specification
VB_SPEC = LanguageSpec(
    ts_language="vb",
    symbol_node_types={
        "class_block": "class",
        "module_block": "class",
        "structure_block": "type",
        "interface_block": "type",
        "enum_block": "type",
        "method_declaration": "method",
        "constructor_declaration": "method",
        "property_declaration": "method",
        "delegate_declaration": "type",
        "event_declaration": "method",
    },
    name_fields={
        "class_block": "name",
        "module_block": "name",
        "structure_block": "name",
        "interface_block": "name",
        "enum_block": "name",
        "method_declaration": "name",
        "constructor_declaration": "name",
        "property_declaration": "name",
        "delegate_declaration": "name",
        "event_declaration": "name",
        "const_declaration": "name",
    },
    param_fields={
        "method_declaration": "parameters",
        "constructor_declaration": "parameters",
        "property_declaration": "parameters",
        "delegate_declaration": "parameters",
    },
    return_type_fields={
        "method_declaration": "return_type",
        "delegate_declaration": "return_type",
    },
    docstring_strategy="preceding_comment",
    decorator_node_type="attribute_block",
    container_node_types=[
        "class_block",
        "module_block",
        "structure_block",
        "interface_block",
    ],
    constant_patterns=["const_declaration"],
    type_patterns=[
        "structure_block",
        "interface_block",
        "enum_block",
        "delegate_declaration",
    ],
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
    "csharp": CSHARP_SPEC,
    "vb": VB_SPEC,
}


CANONICAL_LANGUAGES = tuple(LANGUAGE_REGISTRY.keys())


# Aliases that map to one canonical language
LANGUAGE_ALIASES = {
    "c#": "csharp",
    "cs": "csharp",
    "csharp": "csharp",
    "vb": "vb",
    "vbnet": "vb",
    "visualbasicnet": "vb",
    "visualbasic": "vb",
}


# Aliases that map to a language family
LANGUAGE_FAMILY_ALIASES = {
    "dotnet": {"csharp", "vb"},
    ".net": {"csharp", "vb"},
    "netframework": {"csharp", "vb"},
    ".netframework": {"csharp", "vb"},
    "aspnet": {"csharp", "vb"},
    "asp.net": {"csharp", "vb"},
    "aspnetframework": {"csharp", "vb"},
    "asp.netframework": {"csharp", "vb"},
}


def normalize_language_name(language: str) -> str:
    """Normalize a language or alias for lookup."""
    return language.strip().lower().replace(" ", "").replace("_", "").replace("-", "")


def resolve_language_alias(language: str) -> Optional[str]:
    """Resolve a direct alias to one canonical language."""
    normalized = normalize_language_name(language)

    if normalized in LANGUAGE_REGISTRY:
        return normalized
    if normalized in LANGUAGE_ALIASES:
        return LANGUAGE_ALIASES[normalized]
    return None


def resolve_language_filter(language: Optional[str]) -> Optional[set[str]]:
    """Resolve a language filter into canonical languages."""
    if language is None:
        return None

    normalized = normalize_language_name(language)

    direct = resolve_language_alias(normalized)
    if direct:
        return {direct}

    if normalized in LANGUAGE_FAMILY_ALIASES:
        return set(LANGUAGE_FAMILY_ALIASES[normalized])

    return None


def supported_language_filters() -> list[str]:
    """Return all accepted language filter values."""
    values = set(CANONICAL_LANGUAGES)
    values.update(LANGUAGE_ALIASES.keys())
    values.update(LANGUAGE_FAMILY_ALIASES.keys())
    return sorted(values)
