"""Parsers for Quartus 17 report files, seedy_sta.tcl output and DSE CSV exports."""
import csv
import io
import math
import os
import re

KINDS = ("setup", "hold", "recovery", "removal")


# ---------------------------------------------------------------- value normalisation
def num(text):
    """'"35,081"' / '78.411 MHz' / '-0.5' / '--' -> float or None."""
    if text is None:
        return None
    t = str(text).strip().strip('"').replace(",", "")
    t = re.sub(r"\s*(MHz|ns|MB|%)$", "", t)
    if t in ("", "--", "n/a", "N/A"):
        return None
    try:
        return float(t)
    except ValueError:
        return None


def hms(text):
    """'00:15:39' -> seconds (int)."""
    t = str(text).strip()
    parts = t.split(":")
    if len(parts) != 3:
        return None
    h, m, s = (int(p) for p in parts)
    return h * 3600 + m * 60 + s


def fmt_hms(seconds):
    if seconds is None:
        return ""
    s = int(round(seconds))
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"


def geomean(values):
    vals = [v for v in values if v is not None and v > 0]
    if not vals:
        return None
    return math.exp(sum(math.log(v) for v in vals) / len(vals))


# ---------------------------------------------------------------- Quartus text reports
def fit_summary(text):
    """<rev>.fit.summary -> utilization dict."""
    kv = {}
    for line in text.splitlines():
        if " : " in line:
            k, v = line.split(" : ", 1)
            kv[k.strip()] = v.strip()

    def used(key):
        v = kv.get(key)
        return None if v is None else num(v.split("/")[0])

    return {
        "status": kv.get("Fitter Status", ""),
        "quartus_version": kv.get("Quartus Prime Version", ""),
        "device": kv.get("Device", ""),
        "alms": used("Logic utilization (in ALMs)"),
        "registers": used("Total registers"),
        "pins": used("Total pins"),
        "block_memory_bits": used("Total block memory bits"),
        "ram_blocks": used("Total RAM Blocks"),
        "dsp_blocks": used("Total DSP Blocks"),
        "plls": used("Total PLLs"),
    }


STA_SUMMARY_RE = re.compile(r"^Type\s*:\s*(\S.*?)\s+'(.*)'\s*$")


def sta_summary(text):
    """<rev>.sta.summary -> [{kind, clock, slack, tns}] (worst over all corners, per clock)."""
    out, cur = [], None
    for line in text.splitlines():
        m = STA_SUMMARY_RE.match(line.strip())
        if m:
            kind = m.group(1).strip().lower()
            cur = {"kind": kind.replace(" ", "_"), "clock": m.group(2), "slack": None, "tns": None}
            out.append(cur)
        elif cur and line.startswith("Slack"):
            cur["slack"] = num(line.split(":", 1)[1])
        elif cur and line.startswith("TNS"):
            cur["tns"] = num(line.split(":", 1)[1])
    return out


def _rpt_table(text, title):
    """Rows of a ';'-delimited Quartus report panel, as lists of stripped cells (header first)."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.startswith("; " + title) and line.rstrip().endswith(";") and \
                line.strip("; ").strip() == title:
            rows = []
            for row in lines[i + 2:]:
                if row.startswith("+"):
                    continue
                if not row.startswith(";"):
                    break
                rows.append([c.strip() for c in row.strip().strip(";").split(";")])
            return rows
    return []


def flow_rpt(text):
    """<rev>.flow.rpt -> {runtime_s: {module: s}, peak_mem_mb: {module: MB}, total_s}."""
    rows = _rpt_table(text, "Flow Elapsed Time")
    runtime, peak = {}, {}
    for r in rows[1:]:
        if len(r) < 4:
            continue
        runtime[r[0]] = hms(r[1])
        if num(r[3]) is not None:
            peak[r[0]] = num(r[3])
    return {"runtime_s": runtime, "peak_mem_mb": peak, "total_s": runtime.get("Total")}


# ---------------------------------------------------------------- seedy_sta.tcl output
def sta_tsv(text):
    """Records written by quartus/seedy_sta.tcl."""
    res = {"corners": [], "clocks": [], "fmax": [], "paths": [], "watch": [], "nowatch": []}
    for line in text.splitlines():
        if not line.strip():
            continue
        f = line.split("\t")
        tag = f[0]
        if tag == "corner":
            res["corners"].append(f[1])
        elif tag == "clock":
            res["clocks"].append({"corner": f[1], "kind": f[2], "clock": f[3],
                                  "slack": num(f[4]), "tns": num(f[5])})
        elif tag == "fmax":
            res["fmax"].append({"corner": f[1], "clock": f[2], "fmax": num(f[3]),
                                "restricted": num(f[4])})
        elif tag == "path":
            res["paths"].append({"corner": f[1], "kind": f[2], "slack": num(f[3]), "from": f[4],
                                 "to": f[5], "launch": f[6], "latch": f[7]})
        elif tag == "watch":
            res["watch"].append({"glob": f[1], "dir": f[2], "corner": f[3], "kind": f[4],
                                 "slack": num(f[5]), "from": f[6], "to": f[7],
                                 "launch": f[8], "latch": f[9]})
        elif tag == "nowatch":
            res["nowatch"].append(f[1])
    return res


LEGACY_ROW = re.compile(r"^\s*(-?\d+\.\d+)\s+(.+?) -> (.+)$")


def legacy_paths(text, glob="*ramimg*"):
    """full.tcl's full-timing.txt (the 2026-10-02 manual run) -> same shape as sta_tsv()."""
    res = {"corners": [], "clocks": [], "fmax": [], "paths": [], "watch": [], "nowatch": []}
    cur = None
    for line in text.splitlines():
        if line.startswith("=="):
            m = re.match(r"^== (\S+) (setup|hold)(.*)$", line)
            cond, kind, rest = m.group(1), m.group(2), m.group(3)
            if cond not in res["corners"]:
                res["corners"].append(cond)
            d = re.search(r"\b(from|to)\b", rest)
            if "no registers" in rest:
                cur = None
                if glob not in res["nowatch"]:
                    res["nowatch"].append(glob)
            elif d:
                cur = ("watch", cond, kind, d.group(1))
            else:
                cur = ("path", cond, kind, None)
            continue
        m = LEGACY_ROW.match(line)
        if not m or cur is None:
            continue
        rec = {"corner": cur[1], "kind": cur[2], "slack": float(m.group(1)), "from": m.group(2).strip(),
               "to": m.group(3).strip(), "launch": "", "latch": ""}
        if cur[0] == "path":
            res["paths"].append(rec)
        else:
            rec.update({"glob": glob, "dir": cur[3]})
            res["watch"].append(rec)
    return res


# ---------------------------------------------------------------- DSE CSV exports
def dse_csv(path):
    """A quartus_dse --report CSV: first line is a title, then the header. -> (header, rows)."""
    with open(path, newline="") as fh:
        lines = fh.read().splitlines()
    rdr = csv.reader(io.StringIO("\n".join(lines[1:])))
    rows = [r for r in rdr if r]
    return rows[0], rows[1:]


def dse_point_index(name):
    """'dse1_SNES_17' -> 17 (1-based position in that invocation's seed list)."""
    m = re.search(r"_(\d+)$", name)
    if not m:
        raise ValueError(f"unexpected DSE point name {name!r}")
    return int(m.group(1))


def read_text(path):
    if not os.path.isfile(path):
        return None
    with open(path, errors="replace") as fh:
        return fh.read()
