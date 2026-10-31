"""Shared bibliographic evidence, review audit and evaluation primitives.

The candidate reference function is used for benchmark retrieval coverage and
disk-search equivalence tests. Runtime scoring is the learned ai_model classifier.
"""
import itertools
import json
import math
import re
from collections import defaultdict
from datetime import datetime, timezone
import Levenshtein

ENGINE_VERSION = "desktop-ai-4.0"
FIELDS = ("title", "authors", "venue", "year")
STOP = set("a an the of on in for and to with using via from by at is are as its based new study analysis approach method system model data learning".split())

def now():
    return datetime.now(timezone.utc).isoformat()


def missing(value):
    return value is None or str(value).strip().casefold() in {"", "nan", "none", "null", "unknown", "-", "—"}


def norm(value):
    return "" if missing(value) else str(value).strip().casefold()


def author_tokens(value):
    # Unicode letters; initials are omitted. This is name overlap, not identity resolution.
    text = re.sub(r"\([^)]*\)", " ", norm(value))
    return {t for t in re.findall(r"[^\W\d_]+", text, flags=re.UNICODE)
            if len(t) > 1 and t not in {"and", "et", "al"}}


def fields(a, b):
    result = dict.fromkeys(FIELDS)
    for key in FIELDS:
        x, y = norm(a.get(key)), norm(b.get(key))
        if not x or not y:
            continue
        if key == "title":
            result[key] = 1 - Levenshtein.distance(x, y) / max(len(x), len(y))
        elif key == "authors":
            sx, sy = author_tokens(x), author_tokens(y)
            result[key] = len(sx & sy) / len(sx | sy) if sx | sy else None
        elif key == "year":
            # Only integral numeric years are compared; do not invent missing years.
            try:
                nx, ny = float(x), float(y)
                if math.isfinite(nx) and math.isfinite(ny) and nx.is_integer() and ny.is_integer():
                    result[key] = float(nx == ny)
            except ValueError:
                pass
        else:
            result[key] = float(x == y)
    return result


def tokens(title):
    return sorted(set(t for t in re.findall(r"\w+", norm(title), flags=re.UNICODE)[:40]
                      if len(t) > 2 and t not in STOP))[:12]


def candidates(records, max_pairs=500, budget=3000000):
    """Bound comparisons, not total memory or reading time. Report truncation.

    Exact-title groups are considered first. Large groups use star links, which
    preserve connectivity but do not enumerate every pair. Token blocks larger
    than 100 are skipped. This deliberately favors a bounded review queue.
    """
    if not 1 <= max_pairs <= 100000 or not 1 <= budget <= 3000000:
        raise ValueError("Invalid candidate limits.")
    titles = [norm(r.get("title")) for r in records]
    exact, inverted = defaultdict(list), defaultdict(list)
    for i, title in enumerate(titles):
        if title:
            exact[title].append(i)
        for token in tokens(title):
            inverted[token].append(i)
    seen, found = set(), {}
    stats = {"records": len(records), "comparison_budget": budget, "iterations": 0,
             "compared_pairs": 0, "oversized_token_blocks": sum(len(v) > 100 for v in inverted.values()),
             "large_exact_groups": sum(len(v) > 100 for v in exact.values()), "budget_reached": False,
             "max_pairs": max_pairs, "title_prefilter": .5}

    def proposed():
        for ids in exact.values():
            if len(ids) > 100:
                yield from ((ids[0], j) for j in ids[1:])
            elif len(ids) > 1:
                yield from itertools.combinations(ids, 2)
        for ids in sorted((v for v in inverted.values() if 2 <= len(v) <= 100), key=lambda v: (len(v), v)):
            yield from itertools.combinations(ids, 2)

    for i, j in proposed():
        if stats["iterations"] >= budget:
            stats["budget_reached"] = True
            break
        stats["iterations"] += 1
        key = (min(i, j), max(i, j))
        if key in seen:
            continue
        seen.add(key)
        x, y = titles[i], titles[j]
        size = max(len(x), len(y))
        if not size or abs(len(x) - len(y)) / size >= .5:
            continue
        sim = 1 - Levenshtein.distance(x, y) / size
        stats["compared_pairs"] += 1
        if sim > .5:
            found[key] = sim
    ranked = sorted(found, key=lambda pair: (-found[pair], pair))
    stats.update(eligible_pairs=len(ranked), returned_pairs=min(len(ranked), max_pairs), queue_truncated=len(ranked) > max_pairs)
    return [list(pair) for pair in ranked[:max_pairs]], stats


def pair_result(dataset, session, pair):
    from ai_model import explain
    return explain(dataset["pair_features"](pair), session["ai_model"])


def latest_decisions(session):
    result = {}
    for event in session["events"]:
        result[tuple(event["pair"])] = event
    return result


def review(dataset, session, pair, decision):
    if decision not in {"accept", "reject", "skip"} or list(pair) not in session["pairs"]:
        raise ValueError("Choose an available pair and accept, reject or skip.")
    result = pair_result(dataset, session, pair)
    event = {"timestamp": now(), "pair": list(pair), "decision": decision, "machine": result}
    session["events"].append(event)
    return event


def metrics(scores, labels, threshold):
    if len(scores) != len(labels):
        raise ValueError("Scores and labels must have equal length.")
    tp = fp = fn = tn = 0
    for score, label in zip(scores, labels):
        pred = score > threshold
        tp += int(pred and label); fp += int(pred and not label)
        fn += int(not pred and label); tn += int(not pred and not label)
    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn,
            "precision": tp / (tp + fp) if tp + fp else 0,
            "recall": tp / (tp + fn) if tp + fn else 0,
            "f1": 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else 0}


def select_threshold(scores, labels, current):
    """Evaluate every distinct score boundary for the strict score > threshold rule.

    Ties prefer the threshold closest to current, then the higher threshold.
    No arbitrary 0.01 grid; sorting and grouped cumulative counts are O(n log n).
    """
    if len(scores) != len(labels) or not scores:
        raise ValueError("Scores and labels must have the same nonzero length.")
    if any(not math.isfinite(s) or not 0 <= s <= 1 for s in scores):
        raise ValueError("Scores must be finite values in [0, 1].")
    if any(y not in (0, 1, False, True) for y in labels):
        raise ValueError("Labels must be binary.")
    ordered = sorted(zip(scores, labels))
    thresholds = sorted(set([0.0, 1.0, current, *scores]))
    positive = sum(labels); negative = len(labels)-positive
    tp, fp, fn, tn, index = positive, negative, 0, 0, 0
    best = None
    for threshold in thresholds:
        while index < len(ordered) and ordered[index][0] <= threshold:
            if ordered[index][1]: tp -= 1; fn += 1
            else: fp -= 1; tn += 1
            index += 1
        f1 = 2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else 0.0
        key = (f1, -abs(threshold-current), threshold)
        if best is None or key > best[0]: best = (key, threshold)
    return best[1], len(thresholds)


def export_session(session):
    return json.dumps(session, indent=2, ensure_ascii=False, allow_nan=False).encode("utf-8")

