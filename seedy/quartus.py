"""Work-copy preparation and .qsf edits (no Quartus needed; runs on the host)."""
import glob
import os
import re

from seedy import files

# [ \t] rather than \s so a match never swallows neighbouring lines; \r? keeps CRLF files intact
SEED_RE = re.compile(r"^[ \t]*set_global_assignment[ \t]+-name[ \t]+SEED[ \t]+([^\s#]+)[^\r\n]*?(\r?)$", re.M | re.I)
SEED_LINE_RE = re.compile(r"^[ \t]*set_global_assignment[ \t]+-name[ \t]+SEED[ \t][^\n]*\n?", re.M | re.I)
NPP_RE = re.compile(r"^[ \t]*set_global_assignment[ \t]+-name[ \t]+NUM_PARALLEL_PROCESSORS[ \t][^\n]*\n?", re.M | re.I)
PRE_FLOW_RE = re.compile(r'PRE_FLOW_SCRIPT_FILE\s+"?quartus_sh:([^"\s]+)"?', re.I)
CLOCK_SECONDS_RE = re.compile(r"\[\s*clock\s+seconds\s*\]")


def find_project(root):
    """The single *.qpf at the repo root -> project name."""
    qpfs = sorted(glob.glob(os.path.join(root, "*.qpf")))
    names = [os.path.basename(p)[:-4] for p in qpfs]
    # MiSTer repos often carry a <name>_Q13.qpf for the old toolchain; never pick it
    main = [n for n in names if not n.endswith("_Q13")]
    if len(main) != 1:
        raise SystemExit(f"cannot pick a project from {names}; set the 'project' input")
    return main[0]


def qsf_path(root, revision):
    return os.path.join(root, revision + ".qsf")


def read_seed(qsf_text):
    """The .qsf's own SEED (Quartus default is 1 when absent; the last assignment wins)."""
    m = SEED_RE.findall(qsf_text)
    return int(m[-1][0]) if m else 1


def _eol(text):
    return "\r\n" if "\r\n" in text else "\n"


def set_seed(qsf_text, seed):
    """Rewrite the SEED assignment in place (minimal diff), drop duplicates, or append one."""
    line = f"set_global_assignment -name SEED {int(seed)}"
    hits = list(SEED_RE.finditer(qsf_text))
    if not hits:
        eol = _eol(qsf_text)
        sep = "" if qsf_text.endswith("\n") or not qsf_text else eol
        return qsf_text + sep + line + eol
    keep = hits[-1]
    out = qsf_text[:keep.start()] + line + keep.group(2) + qsf_text[keep.end():]
    # remove earlier duplicates, whole lines, back to front so offsets stay valid
    for m in reversed(list(SEED_LINE_RE.finditer(out[:keep.start()]))):
        out = out[:m.start()] + out[m.end():]
    return out


def set_threads(qsf_text, threads):
    out = NPP_RE.sub("", qsf_text)
    eol = _eol(qsf_text)
    sep = "" if out.endswith("\n") or not out else eol
    return out + sep + f"set_global_assignment -name NUM_PARALLEL_PROCESSORS {int(threads)}" + eol


def pre_flow_scripts(root):
    """Tcl files named by PRE_FLOW_SCRIPT_FILE anywhere in the project's .qsf/.qip/.tcl files."""
    found = set()
    for pat in ("*.qsf", "*.qip", "**/*.qip", "**/*.tcl"):
        for p in glob.glob(os.path.join(root, pat), recursive=True):
            try:
                text = files.read(p, errors="replace")
            except OSError:
                continue
            for m in PRE_FLOW_RE.finditer(text):
                cand = os.path.join(root, m.group(1))
                if os.path.isfile(cand):
                    found.add(os.path.normpath(cand))
    default = os.path.join(root, "sys", "build_id.tcl")
    if os.path.isfile(default):
        found.add(os.path.normpath(default))
    return sorted(found)


def pin_build_date(root, epoch):
    """Make MiSTer's build_id.tcl write a fixed date: the date is design content (CONF_STR ROM)."""
    patched = []
    for p in pre_flow_scripts(root):
        text = files.read(p)
        new = CLOCK_SECONDS_RE.sub(str(int(epoch)), text)
        if new != text:
            files.write(p, new)
            patched.append(os.path.relpath(p, root))
    return patched


def prepare(root, revision, seed, threads, epoch):
    """Set SEED and thread count in the revision .qsf and pin the build date."""
    q = qsf_path(root, revision)
    text = files.read(q)
    text = set_threads(set_seed(text, seed), threads)
    files.write(q, text)
    return {"qsf": os.path.basename(q), "seed": seed, "threads": threads,
            "build_date_patched": pin_build_date(root, epoch)}
