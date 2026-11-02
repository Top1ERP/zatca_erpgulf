"""Verify pinned upstream field coverage without a site, network or writes.

Read exactly seven public DocType JSON files. SHA checks and selected-field
comparison bind the output to the reviewed fixture. This is source metadata
coverage, not applied customization, runtime, accounting or ZATCA acceptance.
"""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

from zatca_erpgulf.zatca_erpgulf.calculation_precision import PARENT_CURRENCY_SCOPES
from zatca_erpgulf.zatca_erpgulf.financial_source_observation import HEADER_FIELDS, TABLE_FIELDS, _child_type

ORACLE = Path(__file__).resolve().parents[1] / "zatca_erpgulf/zatca_erpgulf/tests/erpnext_currency_fields_oracle.json"


def audit(source_root, erp_major, *, flat=False):
    """Accept repository root, or an explicitly flat cache; never discover sites."""
    if type(erp_major) is not int or erp_major not in (15,16) or type(flat) is not bool:
        raise ValueError("currency_inventory_arguments")
    record = json.loads(ORACLE.read_text())
    sources = [row for row in record["sources"] if row["erp_major"] == erp_major]
    manifests = {dt:HEADER_FIELDS for dt in ("Sales Invoice","POS Invoice")}
    for root in ("Sales Invoice","POS Invoice"):
        for table,names in TABLE_FIELDS.items():
            if not table.startswith("custom_"):manifests[_child_type(root,table)] = names
    if len(sources) != 7 or {row["doctype"] for row in sources} != set(manifests):
        raise ValueError("currency_inventory_manifest")
    counts = Counter()
    for source in sources:
        relative = Path(source["path"])
        expected = "erpnext/accounts/doctype/" + source["doctype"].lower().replace(" ","_")
        expected += "/" + source["doctype"].lower().replace(" ","_") + ".json"
        if source["path"] != expected:
            raise ValueError("currency_inventory_manifest")
        path = Path(source_root) / (relative.name if flat else relative)
        raw = path.read_bytes()
        if len(raw)>2*1024*1024 or hashlib.sha256(raw).hexdigest() != source["sha256"]:
            raise ValueError("currency_inventory_source_mismatch")
        document = json.loads(raw)
        if source["doctype"] in ("Sales Invoice","POS Invoice"):
            link = next((df for df in document["fields"] if df["fieldname"] == "party_account_currency"),None)
            projected = None if link is None else {key:link[key] for key in ("fieldname","fieldtype","options","hidden","read_only") if key in link}
            if projected != source.get("owner_link") or link is None or link["fieldtype"] != "Link" or link.get("options") != "Currency":
                raise ValueError("currency_inventory_party_link")
        selected = [{key:df[key] for key in ("fieldname","fieldtype","options","precision") if key in df}
            for df in document["fields"] if df["fieldname"] in manifests[source["doctype"]] and df["fieldtype"] == "Currency"]
        if document["name"] != source["doctype"] or selected != source["fields"]:
            raise ValueError("currency_inventory_fields_mismatch")
        counts.update(df.get("options") for df in selected)
    unsupported = sorted(str(option) for option in counts if option not in PARENT_CURRENCY_SCOPES)
    return dict(erp_major=erp_major, verified_files=len(sources), currency_fields=sum(counts.values()),
        option_counts=dict(counts), unsupported_options=unsupported)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root",required=True,type=Path)
    parser.add_argument("--erp-major",required=True,type=int,choices=(15,16))
    parser.add_argument("--flat",action="store_true",help="Read an explicit flat JSON cache instead of a repository tree.")
    args = parser.parse_args()
    report = audit(args.source_root,args.erp_major,flat=args.flat)
    print(json.dumps(report,sort_keys=True))
    return 1 if report["unsupported_options"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
