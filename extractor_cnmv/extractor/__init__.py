"""extractor — Pipeline de extraccion de folletos CNMV a JSON canonico (55 keys)."""

from .assembler import extract, to_json, build_record
from .schema import KEYS_ORDER, empty_record, DEFAULTS, TIPONOT_CODES
from .segmenter import segment, Segment, FolletoSegmentation
from .validators import validate

__all__ = [
    "extract", "to_json", "build_record",
    "KEYS_ORDER", "empty_record", "DEFAULTS", "TIPONOT_CODES",
    "segment", "Segment", "FolletoSegmentation",
    "validate",
]
