"""Rebuild a revision from the immutable original plus ALL effective notices."""
import hashlib
import re
from datetime import date
from .store import canonical

LABELS = {"generative_ai_policy": "生成AI利用のFAQ", "maintenance_notice": "システムメンテナンス告知",
          "multilingual_evaluation": "多言語能力評価の案内", "fee_refund": "検定料返還の案内", "quota":"募集人員の根拠訂正"}


def revise_article(base, records, as_of, previous_id=None, revision_event_id=None):
    applicable = sorted([r for r in records if r["case_id"] == base["case_id"] and
                         (not r.get("replaces_evidence_ids") or any("["+eid+"]" in base["text"] for eid in r["replaces_evidence_ids"]))], key=lambda x: x["logical_id"])
    if not applicable: raise ValueError("no applicable notices")
    paragraphs, refs, corrections, faq_paragraphs = [], [], [], []
    for r in applicable:
        if r["temporal_status"] == "deadline_elapsed" and date.fromisoformat(r["value"]["deadline"]) >= as_of:
            raise ValueError("cannot describe a future deadline as elapsed")
        cite = "[" + r["evidence_id"] + "]"
        source_paragraph = []
        for sentence in r["sentences"]:
            # Keep the amount's citation adjacent for the legacy proximity check too.
            sentence = re.sub(r"(\d[\d,]*(?:円|名|人|字))", lambda m: m[0] + cite, sentence)
            source_paragraph.append(sentence.rstrip("。") + cite + "。")
        if r.get("replaces_evidence_ids"):
            corrections.append((r," ".join(source_paragraph)))
        elif r.get('condition_profile')=='tsukuba-ac-faq-v1':
            from .faq_policy import validate_condition_bindings
            validate_condition_bindings(r)
            faq_paragraphs.append(' '.join(source_paragraph))
        else:
            paragraphs.append(" ".join(source_paragraph))
        kind = "公式告知 PDF" if r["source_kind"] == "pdf" else "公式FAQ・お知らせ HTML"
        location = " p." + "・".join(str(p) for p in sorted({p["page"] for p in r["proofs"]})) if r["source_kind"] == "pdf" else "（本文の該当節）"
        refs.append(f"- {cite} {LABELS.get(r['fact_key'], r['fact_key'])}：{kind}{location}：{r['source_url']}")
    section = ("\n\n## 公式の追加案内・FAQを踏まえた補足\n\n" + "\n\n".join(paragraphs)) if paragraphs else ""
    change_note = "根拠の訂正を反映し、旧版は履歴に保持しています。" if corrections else "追加告知とFAQを別の根拠として追記しました。募集要項本体の根拠は保持しています。"
    history = "\n\n## 改訂履歴\n\n作業基準日：" + as_of.isoformat() + "。" + change_note + "未公開草案です。\n"
    if "## 根拠資料" not in base["text"]: raise ValueError("base article missing source section")
    base_text=re.sub(r"作業基準日[：:]\s*\d{4}-\d{2}-\d{2}。?","",base["text"],count=1)
    body, bibliography = base_text.split("## 根拠資料", 1)
    removed=set()
    for record,replacement in corrections:
        ancestors=set(record["replaces_evidence_ids"]); new_blocks=[]; replaced=False
        for block in body.split("\n\n"):
            cited=set(re.findall(r"\[(EV-[A-Za-z0-9_-]+)\]",block))
            if cited & ancestors:
                if cited - ancestors: raise ValueError("mixed-evidence paragraph needs explicit source-bound rewrite")
                if not replaced:new_blocks.append(replacement);replaced=True
                removed |= cited
            else:new_blocks.append(block)
        if not replaced: raise ValueError("correction target absent from base article")
        body="\n\n".join(new_blocks)
        bibliography="\n".join(line for line in bibliography.splitlines() if not any("["+eid+"]" in line for eid in ancestors))
    if faq_paragraphs:
        marker=re.search(r'^###[^\n]*（編集上の助言）[^\n]*$',body,re.M)
        if marker is None:raise ValueError('FAQ editorial position needs review')
        faq_section='## 提出書類と生成AIの条件・例外（公式FAQ）\n\n'+'\n\n'.join(faq_paragraphs)+'\n\n'
        body=body[:marker.start()]+faq_section+body[marker.start():]
    text = body.rstrip() + section + history + "\n## 根拠資料" + bibliography.rstrip() + "\n" + "\n".join(refs) + "\n"
    template='notice-faq-conditions-v1' if faq_paragraphs else 'notice-article-v5'
    identity=[base, applicable, as_of.isoformat(), previous_id, template]
    if revision_event_id:identity.append(revision_event_id)
    digest = hashlib.sha256(canonical(identity).encode()).hexdigest()
    return dict(base, article_id=base["article_id"] + ":revision:" + digest[:16],
                base_article_id=base["article_id"], parent_article_id=previous_id or base["article_id"], text=text,
                evidence_ids=sorted((set(base["evidence_ids"])-removed) | {r["evidence_id"] for r in applicable}),
                claims=[c for c in base.get("claims",[]) if c.get("evidence_id") not in removed] +
                       [{"key":r["fact_key"],"evidence_id":r["evidence_id"],"text":" ".join(r["sentences"])} for r in applicable],
                as_of=as_of.isoformat(), revision_hash=digest, publish_allowed=False,
                **({'revision_event_id':revision_event_id} if revision_event_id else {}))
