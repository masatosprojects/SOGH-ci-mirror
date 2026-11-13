# CMD-WORK-20261107-001

Work-owned product export candidate and connection tests. Contract/QA source stays on PR #193, head `945971896fbf80b327d20bd05b10af4b7b4b7a1b`. This branch is stacked on #193; it must not be merged before the dependency is accepted. Observed master `c123f56d506e1ace98ce276dfebf219c8b1c7849`, strategy STR-053. M1 2/8 NOT ACCEPTED.

## Result

- G-05 #191 head `6ec3b67179f2d4825fcd3dd8621a148279c7455f`: the seven previously reported negative cases were re-evaluated at the new head, 0 PASS / 7 FAIL. Unapproved pin, unknown/null/missing scope label, invalid proof dict, offset drift, and ordinary registration with ambiguous heads still pass. Technical disposition REVISE. Normal authority/storage and original position-verification event remain BLOCKED. No product caller of register_alias was found.
- g3 #193 behavior is technically acceptable as an isolation interface, with storage/approval/F-2 acceptance still BLOCKED. This candidate uses its exact reference reader instead of implementing another history resolver.
- Work's two existing active export entry points now check citation relations, case, scope and recorded positions through read_cited_evidence with consumer expectations. Historical articles are refused on this active-only path. Ordinary legacy export articles without evidence_ids are read from their existing [EV-...] text markers, then verified against the stored relation.
- cited_article.py reads requested citations on one snapshot and passes the bound objects to display/export. Consumers only use these values. Tests invoke forbid_current_evidence_reads, and verify_export checks the serialized output.
- Work self-test on Windows / Python 3.12.0 / SQLite 3.42.0: **10 tests PASS, 15 subtests PASS, 0 FAIL, 0 skip**. Subtests are nested cases and are not additional top-level tests. A WAL second connection revoked a restoration during the read: the in-flight result was consistent with its snapshot and a new read was refused.
- Read-only v06 compatibility: **PASS**. 50 evidence / 13 articles, output identical, canonical SHA `eb26aef5c6ec6d70166bf6469ad5ec4db31ad590757fc121c195002abc282458`. Saved DB SHA remained `a8e48b5b16239368e9b5c05aad1dbeb692a657f28dab909bf3c99fff41539578`. This was a current-view read, not a restoration or historical real-copy integration.

## Exact-byte correction

Both prior export hashes are correct for the bytes measured. Work local file: 3610 bytes, LF, SHA256 `c6c1b6a06f5d610cca382c3c0ed8fe70d321bebc4dda74d21144fc5543916d93`. Git blob from #193's Work pipeline: 3665 bytes, 55 CRLF pairs, SHA256 `30b36e45de0fd81215378e8f8783752f63d2ee81cc1a17bb3d9b2d8fd44f8198`. Replacing only CRLF with LF makes the files byte-identical. There was no functional source difference. Earlier statements that left the cause UNKNOWN are superseded by this measurement.

## Reproduce

Use the fixed branch with existing Python dependencies and an approved scratch directory. No automatic package install.

```powershell
$env:TEMP='<approved-scratch>'
$env:TMP=$env:TEMP
python -B -X utf8 -m pytest research/inbox/work-command-202/test_connection.py -q -p no:cacheprovider
python -B -X utf8 research/inbox/work-command-202/g05_negative_probe.py <fixed-pr191-checkout> <new-empty-scratch>
```

The second command tests #191 in a separate checkout; do not accidentally import #193's additive_schema in its place. Both use synthetic DB fixtures from the named dependency. Approval strings in those fixtures are test data. Real history creation, approval storage/signing, actual registration product integration, formal restoration and independent QA are NOT_RUN.

## Edge

#139 head `2a914d7acbfecd3a06d5ec459e4548273985f1de`. The native browser URL confidence blocker is unchanged, so no repeated timed GUI trial was started. OS hidden→visible, 60/300s native behavior NOT_RUN. Follow Issue #75 comment 6697623103: confirm the dedicated loopback tab, switch normally, observe trusted hidden then visible and the matching background request. Stop if target URL or event cannot be established. Injected events and simulated clocks are separate evidence.

## Contract decisions and handoff

G-05: ACCEPT the stale-head SQL condition and per-alias explicit version interface; REVISE the seven rejection boundaries; BLOCKED on authority/storage/verification events. The actual product registration entry is unimplemented; these are direct candidate-interface tests.

g3: ACCEPT the ordinary/restored routing, single-snapshot read, exact bound payload and fail-closed consumer interface for isolated Work tests. Storage migration, provenance authority and semantic scope acceptance remain BLOCKED. Four previously failing Work export conditions are now regression assertions. Formal 0010/DB-17/DB-19, F-2 user acceptance and independent product-path QA remain required.

Next Claude action: review the two active-export changes and cited consumer at the pinned Work head, independently reproduce the tests, and review G-05's unresolved inputs. User approval is still needed for authority/storage, formal restoration and migration, production use and PR merging.
