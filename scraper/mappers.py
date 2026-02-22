"""Data mapping and transformation utilities."""

import re
from typing import List, Dict, Any, Optional


def map_content_to_abstractions(content: str, language: str) -> List[str]:
    """Map content to programming abstractions."""
    abstractions = []
    
    # Common programming abstractions
    abstraction_patterns = {
        "function": [
            r"\bdef\s+\w+",  # Python
            r"\bfunction\s+\w+",  # JavaScript
            r"\bfn\s+\w+",  # Rust
            r"\bfunc\s+\w+",  # Go
            r"\bpublic\s+\w+\s+\w+\s*\([^)]*\)",  # Java
        ],
        "class": [
            r"\bclass\s+\w+",
            r"\binterface\s+\w+",
            r"\bstruct\s+\w+",
            r"\btype\s+\w+",
        ],
        "variable": [
            r"\bvar\s+\w+",
            r"\blet\s+\w+",
            r"\bconst\s+\w+",
            r"\bint\s+\w+",
            r"\bstring\s+\w+",
        ],
        "loop": [
            r"\bfor\s*\(",
            r"\bwhile\s*\(",
            r"\bforeach\s*\(",
        ],
        "condition": [
            r"\bif\s*\(",
            r"\belse\s*{",
            r"\bswitch\s*\(",
        ],
        "exception": [
            r"\btry\s*{",
            r"\bcatch\s*\(",
            r"\bthrow\s+",
        ]
    }
    
    for abstraction, patterns in abstraction_patterns.items():
        for pattern in patterns:
            if re.search(pattern, content, re.IGNORECASE):
                abstractions.append(abstraction)
                break
    
    return list(set(abstractions))


def map_content_to_syntax(content: str, language: str) -> List[str]:
    """Map content to syntax elements."""
    syntax_elements = []
    
    # Language-specific syntax patterns
    syntax_patterns = {
        "python": {
            "indentation": r"^\s+",
            "decorator": r"@\w+",
            "list_comprehension": r"\[.*for.*in.*\]",
            "lambda": r"lambda\s+.*:",
        },
        "javascript": {
            "arrow_function": r"=>",
            "template_literal": r"`.*`",
            "destructuring": r"\{.*\}|\[.*\]",
            "spread_operator": r"\.\.\.",
        },
        "typescript": {
            "type_annotation": r":\s*\w+",
            "interface": r"interface\s+\w+",
            "generic": r"<\w+>",
            "enum": r"enum\s+\w+",
        },
        "rust": {
            "ownership": r"&|&mut",
            "lifetime": r"'\w+",
            "macro": r"!\w+",
            "trait": r"trait\s+\w+",
        },
        "go": {
            "goroutine": r"go\s+\w+",
            "channel": r"chan\s+\w+",
            "defer": r"defer\s+\w+",
            "interface": r"type\s+\w+\s+interface",
        }
    }
    
    if language in syntax_patterns:
        for syntax_type, pattern in syntax_patterns[language].items():
            if re.search(pattern, content, re.IGNORECASE):
                syntax_elements.append(syntax_type)
    
    return syntax_elements


def map_content_to_capabilities(content: str, language: str) -> List[str]:
    """Map content to programming capabilities."""
    capabilities = []
    
    # Common capabilities
    capability_keywords = {
        "file_io": ["file", "read", "write", "open", "close", "stream"],
        "network": ["http", "tcp", "udp", "socket", "request", "response"],
        "database": ["sql", "query", "database", "connection", "transaction"],
        "concurrency": ["thread", "async", "await", "parallel", "mutex"],
        "serialization": ["json", "xml", "yaml", "serialize", "deserialize"],
        "crypto": ["hash", "encrypt", "decrypt", "sign", "verify"],
        "logging": ["log", "debug", "error", "warn", "trace"],
        "testing": ["test", "assert", "mock", "stub", "fixture"],
    }
    
    content_lower = content.lower()
    for capability, keywords in capability_keywords.items():
        if any(keyword in content_lower for keyword in keywords):
            capabilities.append(capability)
    
    return capabilities


def map_framework_patterns(content: str, framework: Optional[str] = None) -> List[str]:
    """Map content to framework-specific patterns."""
    patterns = []
    
    framework_patterns = {
        "react": {
            "hooks": ["useState", "useEffect", "useContext", "useReducer"],
            "components": ["function.*Component", "class.*Component"],
            "jsx": ["<.*>", "</.*>"],
        },
        "vue": {
            "composition_api": ["ref", "reactive", "computed", "watch"],
            "template": ["<template>", "v-if", "v-for", "v-model"],
        },
        "fastapi": {
            "decorators": ["@app.get", "@app.post", "@app.put"],
            "models": ["class.*Model", "BaseModel"],
        },
        "django": {
            "models": ["class.*Model", "models.Model"],
            "views": ["class.*View", "def.*view"],
        },
        "express": {
            "middleware": ["app.use", "router.use"],
            "routes": ["app.get", "app.post", "router.get"],
        }
    }
    
    if framework and framework in framework_patterns:
        for pattern_type, keywords in framework_patterns[framework].items():
            for keyword in keywords:
                if re.search(keyword, content, re.IGNORECASE):
                    patterns.append(pattern_type)
                    break
    
    return patterns


def create_node_mapping(chunk: Dict[str, Any]) -> Dict[str, Any]:
    """Create a complete node mapping from a content chunk."""
    content = chunk.get("content", "")
    language = chunk.get("language", "")
    framework = chunk.get("framework")
    
    # Map to different types of knowledge
    abstractions = map_content_to_abstractions(content, language)
    syntax = map_content_to_syntax(content, language)
    capabilities = map_content_to_capabilities(content, language)
    patterns = map_framework_patterns(content, framework)
    
    # Combine all mappings
    all_tags = abstractions + syntax + capabilities + patterns
    
    # Update the chunk with mappings
    chunk["abstractions"] = abstractions
    chunk["syntax_elements"] = syntax
    chunk["capabilities"] = capabilities
    chunk["framework_patterns"] = patterns
    chunk["tags"].extend(all_tags)
    
    return chunk


def batch_map_chunks(chunks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Apply mapping to a batch of chunks."""
    return [create_node_mapping(chunk) for chunk in chunks]
