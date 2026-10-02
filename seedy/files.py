"""Small file helpers that always close their handles. newline='' keeps CRLF files byte-exact."""
import json


def read(path, **kw):
    with open(path, newline="", **kw) as fh:
        return fh.read()


def write(path, text):
    with open(path, "w", newline="") as fh:
        fh.write(text)


def load_json(path):
    with open(path) as fh:
        return json.load(fh)
