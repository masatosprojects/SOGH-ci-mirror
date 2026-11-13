"""Work consumer of PR #193's proposed citation read contract."""
import json
from src.db_contract.historical_read import (
    forbid_current_evidence_reads, read_cited_evidence, verify_export,
)


def export_cited_article(db, article_id, requests):
    """Read requested citations on one snapshot, then export only the bound objects."""
    owns_snapshot = not db.in_transaction
    if owns_snapshot:
        db.execute("BEGIN")
    try:
        bound = [read_cited_evidence(db, article_id, evidence_id, expect=expect)
                 for evidence_id, expect in requests]
        with forbid_current_evidence_reads(db):
            return render_citations(article_id, bound)
    finally:
        if owns_snapshot and db.in_transaction:
            db.rollback()


def render_citations(article_id, bound):
    """No database argument. Keep every version, source and provenance field."""
    exported = []
    for citation in bound:
        if citation.article_id != article_id:
            raise ValueError("citation belongs to another article")
        item = citation.to_export()
        verify_export(item)
        exported.append(item)
    return {"article_id": article_id, "citations": exported}


def export_json(value):
    for citation in value["citations"]:
        verify_export(citation)
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)
