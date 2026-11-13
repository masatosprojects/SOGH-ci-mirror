import copy, hashlib, json, sqlite3, sys
from contextlib import closing
from pathlib import Path
checkout, scratch = map(Path, sys.argv[1:])
sys.path.insert(0,str(checkout))
from src.db_contract import additive_schema as ad
from tests import test_g05_owner_review as f
from tests import test_additive_schema as t

p=t.build(scratch,"g05-seven.sqlite")
root=t.facts(p)[0]["evidence_id"]
ad.apply(p,confirm_disposable_copy=True)
legacy,base=f.prepare_01(p,root)
fixed={"pinned_evidence_id":"EV-U-head","approved_head_id":"EV-U-head"}
cases=[
("unapproved_pin",legacy,{"pinned_evidence_id":"EV-U-head"}),
("unknown_scope",{**base,"scope":"fiction-incompatible"},{}),
("null_scope",{**base,"scope":None},{}),
("missing_scope",{k:v for k,v in base.items() if k!="scope"},{}),
("invalid_proof_shape",{**base,"proofs":{"bogus":True}},{}),
("offset_drift",{**legacy,"proofs":[{**q,"normalized_start":999,"normalized_end":1000} for q in legacy["proofs"]]},fixed)]
out={}
for name,record,kw in cases:
    before=f.sha(p)
    try:
        f.register(p,"EV-W2-"+name,root,record,**kw)
    except ad.AliasError:
        assert f.sha(p)==before
        out[name]="PASS"
    else:
        out[name]="FAIL"
f.add_revision(p,root,"EV-U-ambiguous",f.SECOND,logical="other")
before=f.sha(p)
try:
    f.register(p,"EV-W2-ambiguous",root,base)
except ad.AliasError:
    assert f.sha(p)==before
    out["ambiguous_ordinary"]="PASS"
else:
    out["ambiguous_ordinary"]="FAIL"
print(json.dumps(out,indent=2))
