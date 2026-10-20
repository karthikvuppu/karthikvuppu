#!/usr/bin/env python3
"""Static checks for the generated workflows.

1. Structure: every connection points at existing nodes, ids unique.
2. If the n8n node packages were unpacked (see REF below), every node type exists, its typeVersion is not
   newer than the package supports, and every parameter name appears in that node's source definition.

REF layout: $N8N_REF/base/package (n8n-nodes-base) and $N8N_REF/lc/package (@n8n/n8n-nodes-langchain), from
`npm pack <pkg> && tar xzf *.tgz`. Without REF only the structural checks run.
"""
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).parent
REF = Path(os.environ.get("N8N_REF", ""))
errors, warns = [], []


def tokens_in(dir_: Path) -> set:
    found = set()
    for f in dir_.rglob("*.js"):
        found |= set(re.findall(r"name: '([^']+)'", f.read_text(errors="ignore")))
        found |= set(re.findall(r"\b([A-Za-z_]\w*):", f.read_text(errors="ignore")))
    return found


def find_node_dir(root: Path, short: str):
    short = short.removesuffix("Tool") if short.endswith("Tool") and short not in ("toolWorkflow",) else short
    for f in (root / "package/dist/nodes").rglob("*.node.js"):
        if re.search(rf"name: '{re.escape(short)}'", f.read_text(errors="ignore")):
            return f
    return None


def max_version(f: Path) -> float:
    nums = []
    for p in f.parent.rglob("*.js"):
        t = p.read_text(errors="ignore")
        for m in re.findall(r"version: \[([^\]]*)\]", t):
            nums += [float(x) for x in re.findall(r"[\d.]+", m) if x.replace(".", "").isdigit()]
        nums += [float(x) for x in re.findall(r"defaultVersion: ([\d.]+)", t)]
        nums += [float(x) for x in re.findall(r"^\s+(\d+(?:\.\d+)?): new ", t, re.M)]
        nums += [float(x) for x in re.findall(r"^\s+(\d+(?:\.\d+)?): ", t, re.M) if "nodeVersions" in t]
    return max(nums) if nums else 0.0


def check(path: Path):
    wf = json.loads(path.read_text())
    names = [n["name"] for n in wf["nodes"]]
    ids = [n["id"] for n in wf["nodes"]]
    if len(set(names)) != len(names):
        errors.append(f"{path.name}: duplicate node names")
    if len(set(ids)) != len(ids):
        errors.append(f"{path.name}: duplicate node ids")
    for src, kinds in wf["connections"].items():
        if src not in names:
            errors.append(f"{path.name}: connection from unknown node {src}")
        for kind, slots in kinds.items():
            for slot in slots:
                for link in slot:
                    if link["node"] not in names:
                        errors.append(f"{path.name}: {src} -> unknown node {link['node']}")
    if not REF.exists():
        return
    for n in wf["nodes"]:
        pkg, short = n["type"].rsplit(".", 1)
        root = REF / ("lc" if pkg.startswith("@n8n/") else "base")
        f = find_node_dir(root, short)
        if not f:
            errors.append(f"{path.name}: node type not found in package: {n['type']}")
            continue
        top = max_version(f)
        if top and n["typeVersion"] > top:
            errors.append(f"{path.name}: {n['name']} typeVersion {n['typeVersion']} > package max {top}")
        known = tokens_in(f.parent)
        # shared option descriptions live beside the node or one level up
        known |= tokens_in(f.parent.parent) if f.parent.name in ("v1", "v2", "V1", "V2", "V3") else set()

        def walk(d, prefix=""):
            for k, v in d.items():
                if k not in known and not k.startswith("__"):
                    warns.append(f"{path.name}: {n['name']}: parameter '{prefix}{k}' not found in node source")
                if isinstance(v, dict) and k not in ("value", "schema"):
                    walk(v, prefix + k + ".")

        walk(n["parameters"])


for p in sorted((HERE / "workflows").glob("*.json")):
    check(p)

print("REF checks:", "on" if REF.exists() else "off (set N8N_REF for parameter-name checks)")
for w in sorted(set(warns)):
    print("WARN ", w)
for e in errors:
    print("ERROR", e)
print(f"{len(errors)} errors, {len(set(warns))} warnings")
sys.exit(1 if errors else 0)
