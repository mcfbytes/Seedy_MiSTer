"""Seed lists, sharding and the baseline cache key."""
import hashlib
import json
import re

from seedy import __version__


def parse_seeds(spec):
    """'1-30' or '1,4,8-12' -> sorted unique list of ints. Seeds must be >= 1."""
    out = set()
    for part in str(spec).replace(" ", "").split(","):
        if not part:
            continue
        if "-" in part:
            lo, hi = part.split("-", 1)
            lo, hi = int(lo), int(hi)
            if hi < lo:
                raise ValueError(f"bad seed range {part!r}")
            out.update(range(lo, hi + 1))
        else:
            out.add(int(part))
    if not out:
        raise ValueError(f"empty seed list {spec!r}")
    if min(out) < 1:
        raise ValueError("seeds must be >= 1")
    return sorted(out)


def format_seeds(seeds):
    """Inverse of parse_seeds: [1,2,3,5] -> '1-3,5'."""
    seeds = sorted(set(seeds))
    parts, start, prev = [], None, None
    for s in seeds + [None]:
        if start is None:
            start = prev = s
        elif s is not None and s == prev + 1:
            prev = s
        else:
            parts.append(str(start) if start == prev else f"{start}-{prev}")
            start = prev = s
    return ",".join(parts)


def shard(seeds, shards):
    """Round-robin split; drops empty shards so the matrix never has idle jobs."""
    shards = max(1, min(int(shards), len(seeds)))
    return [seeds[i::shards] for i in range(shards)]


def cache_key(*, project, revision, baseline_sha, image, seeds, threads, build_epoch, npaths=40):
    """Everything that can change a baseline result. image should be digest-pinned. The full Seedy
    version is included because any parser or STA-script change can change a record."""
    blob = json.dumps({
        "project": project, "revision": revision, "sha": baseline_sha, "image": image,
        "seeds": format_seeds(seeds), "threads": int(threads), "seedy": __version__,
        "build_epoch": int(build_epoch), "npaths": int(npaths),
    }, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:32]


MAX_JOBS = 256  # GitHub Actions' limit on jobs in one matrix


def parse_jobs(jobs, shards, variants):
    """The `jobs` input: a positive number, "max" (one seed per job), or empty for the older
    per-variant `shards` (shards x variants jobs). Returns an int or "max"."""
    jobs = str(jobs or "").strip().lower()
    if not jobs:
        return max(1, int(shards)) * max(1, len(variants))
    if jobs == "max":
        return "max"
    if not jobs.isdigit() or int(jobs) < 1:
        raise ValueError(f"jobs must be a positive number or max, not {jobs!r}")
    return int(jobs)


def split_work(seeds, variants, jobs):
    """Split every (variant, seed) compile into at most `jobs` lists, each mixing the variants.

    While there are no more jobs than seeds, seeds go round-robin to jobs (as `shard` does) and each
    job compiles every variant of its seeds, so baseline and candidate share each runner and drain
    together. With more jobs than seeds the compiles themselves go round-robin, down to one per job.
    Each list is in run order: seed by seed, the variants of a seed one after the other."""
    items = [(v, s) for s in seeds for v in variants]
    n = len(items) if jobs == "max" else int(jobs)
    n = max(1, min(n, len(items), MAX_JOBS))
    if n <= len(seeds):
        return [[(v, s) for s in ss for v in variants] for ss in shard(seeds, n)]
    return [items[i::n] for i in range(n)]


def format_work(items):
    """[("baseline", 1), ("candidate", 1), ("baseline", 3)] -> 'baseline=1,3;candidate=1'."""
    order = list(dict.fromkeys(v for v, _ in items))
    return ";".join(f"{v}={format_seeds([s for vv, s in items if vv == v])}" for v in order)


def parse_work(spec):
    """Inverse of format_work, in run order: seed by seed, variants in the order the spec names them."""
    by = {}
    for part in str(spec).split(";"):
        part = part.strip()
        if not part:
            continue
        v, _, seeds = part.partition("=")
        if not re.fullmatch(r"[a-z]+", v) or not seeds:
            raise ValueError(f"bad work item {part!r}; want variant=seeds")
        if v in by:
            raise ValueError(f"variant {v!r} named twice")
        by[v] = set(parse_seeds(seeds))
    if not by:
        raise ValueError(f"empty work list {spec!r}")
    return [(v, s) for s in sorted(set().union(*by.values())) for v in by if s in by[v]]


def parse_first(spec):
    """'candidate:7,baseline:1' -> [("candidate", 7), ("baseline", 1)], order kept, duplicates dropped."""
    out = []
    for part in str(spec or "").replace(" ", "").split(","):
        if not part:
            continue
        v, _, seed = part.partition(":")
        if not re.fullmatch(r"[a-z]+", v) or not seed.isdigit() or int(seed) < 1:
            raise ValueError(f"bad item {part!r}; want variant:seed")
        if (v, int(seed)) not in out:
            out.append((v, int(seed)))
    return out


def format_first(items):
    return ",".join(f"{v}:{s}" for v, s in items)


def split_with_first(seeds, variants, jobs, first=()):
    """split_work, then the `first` compiles (hunt references) go to the front of the jobs, each to
    the job with the fewest compiles so far (the lowest-numbered on a tie), so they start before anything
    else and keep the jobs even: 31 seeds + 1 reference over 16 jobs is 2 each, one wave.
    Returns [(items, first_items)] per job."""
    first = list(dict.fromkeys(first))
    groups = [[x for x in g if x not in first] for g in split_work(seeds, variants, jobs)] if seeds else []
    groups = [g for g in groups if g] or [[]]
    heads = [[] for _ in groups]
    for x in first:
        i = min(range(len(groups)), key=lambda k: (len(heads[k]) + len(groups[k]), k))
        heads[i].append(x)
    return [(h + g, h) for h, g in zip(heads, groups) if h + g]


def order_work(items, first=()):
    """Run order for one job: the `first` items it holds, in the order given, then the rest."""
    head = [x for x in first if x in items]
    return head + [x for x in items if x not in head]


def matrix(seeds, jobs, variants, first=()):
    """GitHub Actions matrix include list: one entry per job, each a mix of variants. `first`
    (variant, seed) compiles run at the front of their jobs, even past a hunt's stop."""
    inc = []
    for i, (items, head) in enumerate(split_with_first(seeds, variants, jobs, first)):
        work = format_work(items)
        label = work.replace("=", " ").replace(";", " + ")
        entry = {"shard": i, "work": work, "label": label}
        if head:
            entry["first"] = format_first(head)
            entry["label"] = f"{label} (first {' '.join(f'{v} {s}' for v, s in head)})"
        inc.append(entry)
    return {"include": inc}
