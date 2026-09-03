"""ShopSense semantic layer - metric catalog + deterministic SQL builder."""

from .semantic_layer import CompiledQuery, SemanticLayer, SemanticLayerError

__all__ = ["SemanticLayer", "CompiledQuery", "SemanticLayerError"]
