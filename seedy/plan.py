"""Seed lists, sharding and the baseline cache key."""
import hashlib
import json

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


def matrix(seeds, shards, variants):
    """GitHub Actions matrix include list: one entry per variant x shard."""
    inc = []
    for v in variants:
        for i, ss in enumerate(shard(seeds, shards)):
            inc.append({"variant": v, "shard": i, "seeds": format_seeds(ss)})
    return {"include": inc}
