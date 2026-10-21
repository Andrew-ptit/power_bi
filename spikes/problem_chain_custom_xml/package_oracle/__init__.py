"""Independent OOXML/COM oracle for the Problem Chain Custom XML spike."""

from .oracle import (
    MAX_DOCUMENT_BYTES,
    MAX_REVISIONS,
    PROBLEM_CHAIN_NAMESPACE,
    PackageOracleError,
    build_problem_chain_xml,
    canonical_json_bytes,
    inspect_problem_chain_parts,
    parse_problem_chain_xml,
    semantic_workbook_snapshot,
)

__all__ = [
    "MAX_DOCUMENT_BYTES",
    "MAX_REVISIONS",
    "PROBLEM_CHAIN_NAMESPACE",
    "PackageOracleError",
    "build_problem_chain_xml",
    "canonical_json_bytes",
    "inspect_problem_chain_parts",
    "parse_problem_chain_xml",
    "semantic_workbook_snapshot",
]
