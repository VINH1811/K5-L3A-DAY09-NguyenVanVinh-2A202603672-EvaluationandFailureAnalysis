"""CI gate: compare a PR eval report with the main-branch baseline using the metric spec.

    python -m lab9.gate --pr reports/eval_workflow.json --baseline reports/baseline_v1.json

exit 0 = merge, exit 1 = blocked. Safety metrics: max 0, no averaging away.
Capability metrics: meet the floor AND the paired CI of (PR - main) is not entirely below 0.
Thresholds may only get stricter on the same eval-set version (ratchet).
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from lab8.console import utf8_stdio
from lab9 import stats
from lab9.eval import SPEC, load_spec, per_item


def integrity_check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> list[str]:
    """M7 (Expert): refuse to compare reports that cannot be trusted. Return a list of problems
    (empty = trustworthy). A gate that passes a broken report is worse than no gate.
    Must catch at least:
      - any metric value in pr["metrics"] that is NaN or inf
      - len(pr["rows"]) != manifest items x len(manifest seeds)   (dropped / duplicated rows)
      - the (item_id, seed) set of PR differs from the baseline's (cherry-picked seeds/items)
      - pr["evaluator_failures"] non-empty, or a row whose value for a graded spec metric is
        None (a crashed grader silently scores as "missing" and drops out of the mean)
      - base_spec given and a threshold in spec is LOOSER than in base_spec for the same
        eval-set version (ratchet: max may not rise, min may not fall, a blocking metric may
        not become non-blocking, a metric may not disappear; the same for spec["slices"],
        including dropping no_significant_drop)
      - an item's slice tags in PR rows differ from the baseline's (relabelling an item out of a
        slice hides its regression from the slice gate)"""
    problems: list[str] = []
    graded = _graded_ids(spec, base_spec)

    for who, rep in (("PR", pr), ("baseline", base)):
        problems += [f"{who} {p}" for p in _report_problems(rep, graded)]

    # Both reports must cover the same (item, seed) set with the same slice tags.
    pr_keys, base_keys = _row_keys(pr), _row_keys(base)
    if set(pr_keys) != set(base_keys):
        missing, extra = set(base_keys) - set(pr_keys), set(pr_keys) - set(base_keys)
        problems.append(f"(item, seed) set differs from the baseline: {len(missing)} missing "
                        f"{_few(missing)}, {len(extra)} extra {_few(extra)} (dropped or cherry-picked rows)")
    pm, bm = pr.get("manifest") or {}, base.get("manifest") or {}
    for k in ("items", "seeds", "eval_set_sha"):
        if pm.get(k) != bm.get(k):
            problems.append(f"manifest {k} {pm.get(k)!r} != baseline {bm.get(k)!r}")
    base_slices = {k: sorted(r.get("slices") or []) for k, r in base_keys.items()}
    relabelled = sorted(f"{i}@{s}" for (i, s), r in pr_keys.items()
                        if (i, s) in base_slices and sorted(r.get("slices") or []) != base_slices[(i, s)])
    if relabelled:
        problems.append(f"slice tags differ from the baseline on {len(relabelled)} row(s) {_few(relabelled)}")

    if base_spec is not None:
        same_set = pm.get("eval_set_sha") == bm.get("eval_set_sha")
        problems += _ratchet(spec, base_spec, same_eval_set=same_set)
    return problems


def _few(xs, n: int = 3) -> str:
    xs = sorted(f"{x[0]}@{x[1]}" if isinstance(x, tuple) else str(x) for x in xs)
    return "[" + ", ".join(xs[:n]) + (", ..." if len(xs) > n else "") + "]"


def _graded_ids(spec: dict, base_spec: dict | None) -> list[str]:
    """Spec metrics a grader writes into every row (as opposed to report-level aggregates)."""
    from lab9.graders import GRADERS
    ids = [m["id"] for m in spec.get("metrics", [])]
    if base_spec:
        ids += [m["id"] for m in base_spec.get("metrics", []) if m["id"] not in ids]
    return [i for i in ids if i in GRADERS]


def _row_keys(rep: dict) -> dict[tuple[str, int], dict]:
    return {(r.get("item_id"), r.get("seed")): r for r in rep.get("rows") or []}


def _is_bad_number(v) -> bool:
    return isinstance(v, float) and (math.isnan(v) or math.isinf(v))


def _report_problems(rep: dict, graded: list[str]) -> list[str]:
    out: list[str] = []
    rows = rep.get("rows") or []
    man = rep.get("manifest") or {}
    if not rows:
        return ["has no rows"]
    for k, v in (rep.get("metrics") or {}).items():
        if _is_bad_number(v):
            out.append(f"metric {k} is {v} (NaN/inf: a crashed grader or a division by zero)")
        elif v is not None and not isinstance(v, (int, float)):
            out.append(f"metric {k} is not a number: {v!r}")
    want = (man.get("items") or 0) * len(man.get("seeds") or [])
    if len(rows) != want:
        out.append(f"has {len(rows)} rows, manifest says {man.get('items')} items x {len(man.get('seeds') or [])} seeds = {want}")
    keys = [(r.get("item_id"), r.get("seed")) for r in rows]
    dups = sorted({k for k in keys if keys.count(k) > 1})
    if dups:
        out.append(f"has duplicated (item, seed) rows {_few(dups)}")
    seeds = set(man.get("seeds") or [])
    off = sorted({r.get("seed") for r in rows} - seeds)
    if off:
        out.append(f"has rows for seeds {off} not in the manifest")
    if len({r.get("item_id") for r in rows}) != man.get("items"):
        out.append(f"covers {len({r.get('item_id') for r in rows})} items, manifest says {man.get('items')}")
    if rep.get("evaluator_failures"):
        out.append(f"has {len(rep['evaluator_failures'])} evaluator failure(s), e.g. {rep['evaluator_failures'][0]}")
    present = [m for m in graded if any(m in r for r in rows)]
    for m in graded:
        if m not in present:
            continue
        broken = [f"{r.get('item_id')}@{r.get('seed')}" for r in rows if not isinstance(r.get(m), bool)]
        if broken:
            out.append(f"metric {m} has {len(broken)} row(s) without a True/False verdict {_few(broken)} "
                       "(a crashed grader must not drop out of the mean)")
    # The headline numbers must be what the rows say: a hand-edited metric is a forged report.
    if present and all(isinstance(r.get(m), bool) for r in rows for m in present):
        from lab9.eval import aggregate
        k_values = sorted({int(k.rsplit("_", 1)[1]) for k in (rep.get("metrics") or {})
                           if k.startswith(("pass_at_", "pass_hat_")) and k.rsplit("_", 1)[1].isdigit()})
        has_cost = all("cost" in r for r in rows)
        try:
            again = aggregate([r if has_cost else {**r, "cost": 0.0} for r in rows], present, k_values=k_values)
        except (ValueError, ZeroDivisionError) as e:
            return out + [f"metrics cannot be recomputed from rows: {e}"]
        for k, v in (rep.get("metrics") or {}).items():
            if k not in again or (k == "cost_per_success" and not has_cost) or k not in (rep.get("metrics") or {}):
                continue
            w = again[k]
            if v is None or w is None:
                if v != w:
                    out.append(f"metric {k} = {v!r} but the rows give {w!r}")
            elif isinstance(v, (int, float)) and not _is_bad_number(v) and abs(float(v) - float(w)) > 1e-3:
                out.append(f"metric {k} = {v} but the rows give {w} (report edited after the run)")
    return out


def _ratchet(spec: dict, base_spec: dict, same_eval_set: bool = True) -> list[str]:
    """Same eval-set version: thresholds may only get stricter (and nothing may disappear).
    A version label bumped while the reports still run on the SAME eval set (same sha) is not a new
    version, it is a way around the ratchet, so the ratchet still applies."""
    out: list[str] = []
    if spec.get("eval_set_version") != base_spec.get("eval_set_version"):
        if not same_eval_set:
            return []       # a genuinely new eval set starts a new ratchet (needs a new baseline)
        out.append(f"RATCHET eval_set_version {base_spec.get('eval_set_version')} -> "
                   f"{spec.get('eval_set_version')} but the eval set (sha) is unchanged")
        for k in ("eval_set", "labels"):
            if spec.get(k) != base_spec.get(k):
                out.append(f"RATCHET spec {k} changed {base_spec.get(k)} -> {spec.get(k)}")
    out += _ratchet_list("metric", {m["id"]: m for m in spec.get("metrics", [])},
                         {m["id"]: m for m in base_spec.get("metrics", [])}, lambda m: m.get("threshold") or {})
    key = lambda s: f"{s.get('name')}/{s.get('metric')}"
    out += _ratchet_list("slice", {key(s): s for s in spec.get("slices") or []},
                         {key(s): s for s in base_spec.get("slices") or []}, lambda s: s)
    for k in ("seeds",):
        if spec.get(k) != base_spec.get(k):
            out.append(f"RATCHET spec {k} changed {base_spec.get(k)} -> {spec.get(k)} on the same eval-set version")
    return out


# For each threshold key: True = a higher value is stricter, False = a lower value is stricter.
_STRICTER_HIGHER = {"min": True, "max": False, "max_increase": False,
                    "max_new_unreliable": False, "max_new_failing_trials": False}


def _ratchet_list(kind: str, new: dict, old: dict, th_of) -> list[str]:
    out: list[str] = []
    for k, o in old.items():
        n = new.get(k)
        if n is None:
            out.append(f"RATCHET {kind} {k} was removed")
            continue
        if o.get("blocking") and not n.get("blocking"):
            out.append(f"RATCHET {kind} {k} is no longer blocking")
        to, tn = th_of(o), th_of(n)
        for t, higher in _STRICTER_HIGHER.items():
            if t not in to:
                continue
            if t not in tn:
                out.append(f"RATCHET {kind} {k}: {t} {to[t]} was removed")
            elif (tn[t] < to[t]) if higher else (tn[t] > to[t]):
                out.append(f"RATCHET {kind} {k}: {t} loosened {to[t]} -> {tn[t]}")
        if to.get("no_significant_drop") and not tn.get("no_significant_drop"):
            out.append(f"RATCHET {kind} {k}: no_significant_drop was dropped")
    return out


def slice_check(pr: dict, base: dict, spec: dict) -> tuple[list[str], list[str]]:
    """M5 (Advanced): an average can hide a regression on a small, important slice.
    For each entry of spec["slices"] ({"name", "metric", "min"?, "no_significant_drop"?, "blocking"}):
      - value = mean of per_item(pr, metric, slice_name=name)
      - fail if below "min", or if no_significant_drop and the paired CI over the slice's items
        lies entirely below 0
    Return (blocked ids like "slice:money_movement/pass_rate", report lines)."""
    blocked: list[str] = []
    lines: list[str] = []
    bs = spec.get("bootstrap", {})
    for sl in spec.get("slices") or []:
        name, metric = sl["name"], sl["metric"]
        sid = f"slice:{name}/{metric}"
        a, b = per_item(pr, metric, slice_name=name), per_item(base, metric, slice_name=name)
        verdict, note, val = "ok", "", None
        if not a:
            # A slice the PR does not cover cannot be "fine": it hides whatever happened there.
            verdict, note = "missing", "no rows in this slice"
        else:
            val = round(sum(a.values()) / len(a), 4)
            if "min" in sl and val < sl["min"]:
                verdict = "fail"
            if sl.get("no_significant_drop"):
                keys = sorted(set(a) & set(b))
                if keys:
                    d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                                       n_resamples=bs.get("n_resamples", 1000),
                                                       rng=bs.get("rng", 2027))
                    note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
                    if hi < 0:
                        verdict = "fail"
        if verdict != "ok" and sl.get("blocking"):
            blocked.append(sid)
        label = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if sl.get("blocking") else "warn")
        th = {k: sl[k] for k in ("min", "no_significant_drop") if k in sl}
        lines.append(f"  {sid:<38} {val!s:<8} n={len(a):<3} {json.dumps(th):<36} {note:<28} {label}")
    return blocked, lines


def new_unreliable_items(pr: dict, base: dict, metric: str = "pass_rate") -> list[str]:
    """Items that pass `metric` on all seeds in the baseline but not on all seeds in the PR."""
    def all_pass(report: dict) -> dict[str, bool]:
        acc: dict[str, bool] = {}
        for r in report["rows"]:
            acc[r["item_id"]] = acc.get(r["item_id"], True) and bool(r.get(metric))
        return acc
    a, b = all_pass(pr), all_pass(base)
    return sorted(k for k in a.keys() & b.keys() if b[k] and not a[k])


def new_failing_trials(pr: dict, base: dict, metric: str = "pass_rate") -> list[str]:
    """item@seed trials that pass `metric` in the baseline and fail it in the PR."""
    ok_base = {(r["item_id"], r["seed"]) for r in base["rows"] if r.get(metric) is True}
    return [f"{r['item_id']}@{r['seed']}" for r in pr["rows"]
            if (r["item_id"], r["seed"]) in ok_base and r.get(metric) is not True]


def check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> tuple[list[str], list[str]]:
    if pr["manifest"]["eval_set_sha"] != base["manifest"]["eval_set_sha"]:
        return ["eval_set_sha"], ["  EVAL SET differs from the baseline's: re-run the baseline on the same eval set"]
    problems = integrity_check(pr, base, spec, base_spec)
    if problems:
        return ["integrity"], [f"  INTEGRITY {p}" for p in problems]
    blocked, lines = [], []
    bs = spec.get("bootstrap", {})
    for m in spec["metrics"]:
        mid, th, val = m["id"], m.get("threshold", {}), pr["metrics"].get(m["id"])
        verdict, note = "ok", ""
        if val is None:
            verdict = "missing"
        elif "max" in th and val > th["max"]:
            verdict = "fail"
        elif "min" in th and val < th["min"]:
            verdict = "fail"
        elif "max_increase" in th and base["metrics"].get(mid):
            if val > base["metrics"][mid] * (1 + th["max_increase"]):
                verdict = "fail"
        if th.get("no_significant_drop") and val is not None:
            a, b = per_item(pr, mid), per_item(base, mid)
            keys = sorted(set(a) & set(b))
            d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                               n_resamples=bs.get("n_resamples", 1000), rng=bs.get("rng", 2027))
            note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
            if hi < 0:
                verdict = "fail"
        if "max_new_unreliable" in th:
            # Item level pass^k: an item that passed on every seed in the baseline and fails on any
            # seed in the PR is a NEW unreliable item, even when another item got fixed and the
            # average pass^5 stays flat.
            newly = new_unreliable_items(pr, base)
            note = (note + " " if note else "") + f"new unreliable items: {len(newly)}"
            if newly:
                note += f" ({', '.join(newly[:4])}{', ...' if len(newly) > 4 else ''})"
            if len(newly) > th["max_new_unreliable"]:
                verdict = "fail"
        if "max_new_failing_trials" in th:
            # Trial level: with a deterministic agent (A/A delta 0) the same (item, seed) must give the
            # same verdict, so a trial that passes on main and fails in the PR is a regression even if
            # another trial got fixed. With a real LLM this needs a tolerance taken from A/A.
            newly = new_failing_trials(pr, base, mid)
            note = (note + " " if note else "") + f"new failing trials: {len(newly)}"
            if newly:
                note += f" ({', '.join(newly[:3])}{', ...' if len(newly) > 3 else ''})"
            if len(newly) > th["max_new_failing_trials"]:
                verdict = "fail"
        if verdict != "ok" and m.get("blocking"):
            blocked.append(mid)
        label = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if m.get("blocking") else "warn")
        lines.append(f"  {mid:<22} {val!s:<8} {json.dumps(th):<40} {note:<28} {label}")
    if spec.get("slices"):
        sb, sl = slice_check(pr, base, spec)
        blocked += sb
        lines += sl
    return blocked, lines


def main(argv: list[str] | None = None) -> int:
    utf8_stdio()
    ap = argparse.ArgumentParser(prog="lab9.gate")
    ap.add_argument("--pr", required=True)
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--spec", default=str(SPEC))
    ap.add_argument("--base-spec", help="metric spec on main, for the ratchet check (M7)")
    args = ap.parse_args(argv)
    pr = json.loads(Path(args.pr).read_text(encoding="utf-8"))
    base = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    base_spec = load_spec(Path(args.base_spec)) if args.base_spec else None
    blocked, lines = check(pr, base, load_spec(Path(args.spec)), base_spec)
    print(f"gate: PR {pr['run_id']} vs main {base['run_id']} · eval set {pr['manifest']['eval_set_sha']}")
    print("\n".join(lines))
    if blocked:
        print(f"exit 1 — blocked: {', '.join(blocked)}")
        return 1
    print("exit 0 — merge")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
