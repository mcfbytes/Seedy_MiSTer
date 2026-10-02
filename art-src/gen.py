"""Seedy Kun art generator: MiSTer Kun as a back-alley dealer of fitter seeds.

Same pipeline as the Tasty art: MiSTer Kun's paths from the upstream remaster, hand-written SVG
props on top, inkscape for PNGs. Run: python3 art-src/gen.py  (writes ../art and ../art/icons)
Needs mister_kun_fullcolor.svg from https://github.com/baxysquare/mister_kun (set KUN_SVG to its path).
"""
import re, subprocess, os

HERE = os.path.dirname(os.path.abspath(__file__))
ART = os.path.join(HERE, "..", "art")
ICONS = os.path.join(ART, "icons")
KUN_SRC = os.environ.get("KUN_SVG", "/mnt/source/mister-kun-splash/upstream/mister_kun_fullcolor.svg")

src = open(KUN_SRC).read()
PATHS = [p for p in re.findall(r'<path [^>]*/>', src) if 'm-81.806' not in p]
OUTLINE, FILL, FACE = PATHS[0], PATHS[1], PATHS[2:]
FILL_D = re.search(r'd="([^"]*)"', FILL).group(1)
EYE_D = [re.search(r'd="([^"]*)"', p).group(1) for p in FACE if 'fill="#fff"' in p]

PINK = "#e88cb8"; BLACK = "#000"; WHITE = "#efefef"; GREY = "#b3b3b3"
KHAKI = "#cfa86a"; KHAKI_D = "#a8803f"; KHAKI_L = "#e3c48e"
ACCENT = "#f4c430"   # sunflower: the Seedy accent
HAT = "#4b4038"; HAT_D = "#2a231e"; LINING = "#8e2b3a"
RED = "#d9463b"; GREEN = "#3fae5a"; GREEN_D = "#2c7f41"; PAPER = "#fbfbf6"; TAN = "#e8b37a"; POT = "#c96a3d"
S = 'stroke="#000" stroke-width="16" stroke-linejoin="round" stroke-linecap="round"'
S10 = 'stroke="#000" stroke-width="10" stroke-linejoin="round" stroke-linecap="round"'
FONT = 'font-family="Open Sans" font-weight="800" font-style="italic"'
JP = 'font-family="Noto Sans JP Thin" font-weight="800"'

DEFS = f'<defs><clipPath id="body"><path d="{FILL_D}"/></clipPath></defs>'


def seed(x, y, s=1.0, rot=0):
    """A striped sunflower seed."""
    return (f'<g transform="translate({x} {y}) rotate({rot}) scale({s})">'
            f'<path d="M0 -60 C28 -40 34 20 0 60 C-34 20 -28 -40 0 -60 Z" fill="#3a3530" {S10}/>'
            f'<path d="M0 -44 C6 -10 6 20 0 46 M-14 -26 C-12 0 -10 20 -8 34 M14 -26 C12 0 10 20 8 34" '
            f'fill="none" stroke="#f3eee0" stroke-width="7" stroke-linecap="round"/></g>')


# --- the outfit -----------------------------------------------------------------------------------

def coat(open_=False):
    """Trenchcoat over Kun's lower body: clipped to the body, collar popped up past the cheeks."""
    if open_:
        # coat flung open: dark lining in the middle, full of seed packets
        body = f'<rect x="0" y="690" width="1000" height="320" fill="{KHAKI}"/>'
        body += f'<rect x="0" y="690" width="170" height="320" fill="{KHAKI_D}" opacity="0.45"/>'
        body += f'<rect x="830" y="690" width="170" height="320" fill="{KHAKI_D}" opacity="0.45"/>'
        body += f'<path d="M300 690 L700 690 L760 1010 L240 1010 Z" fill="{LINING}" {S}/>'
        body += f'<path d="M0 826 L290 826 L296 866 L0 866 Z" fill="{KHAKI_D}" stroke="#000" stroke-width="10"/>'
        body += f'<path d="M1000 826 L708 826 L702 866 L1000 866 Z" fill="{KHAKI_D}" stroke="#000" stroke-width="10"/>'
        laps = ["M70 730 L150 584 L330 652 L340 700 L300 1010 L240 1010 L230 780 L140 780 Z",
                "M930 730 L850 584 L670 652 L660 700 L700 1010 L760 1010 L770 780 L860 780 Z"]
    else:
        # V neck shows Kun's white shirt and a skinny tie
        body = f'<path d="M0 690 L370 690 L500 820 L630 690 L1000 690 L1000 1010 L0 1010 Z" fill="{KHAKI}" {S}/>'
        body += f'<rect x="0" y="690" width="170" height="320" fill="{KHAKI_D}" opacity="0.45"/>'
        body += f'<rect x="830" y="690" width="170" height="320" fill="{KHAKI_D}" opacity="0.45"/>'
        body += f'<path d="M482 700 L518 700 L512 724 L530 790 L500 818 L470 790 L488 724 Z" fill="{LINING}" stroke="#000" stroke-width="9" stroke-linejoin="round"/>'
        # pocket flaps
        body += f'<path d="M190 900 L330 900 L320 940 L200 940 Z M670 900 L810 900 L800 940 L680 940 Z" fill="{KHAKI_D}" stroke="#000" stroke-width="9" stroke-linejoin="round"/>'
        # belt and buckle
        body += f'<rect x="-20" y="826" width="1040" height="42" fill="{KHAKI_D}" stroke="#000" stroke-width="10"/>'
        body += (f'<rect x="464" y="816" width="72" height="62" rx="10" fill="none" stroke="#000" stroke-width="22"/>'
                 f'<rect x="464" y="816" width="72" height="62" rx="10" fill="none" stroke="{ACCENT}" stroke-width="10"/>'
                 f'<path d="M500 826 L500 868" stroke="#000" stroke-width="10"/>')
        laps = ["M70 730 L150 584 L330 652 L370 690 L500 820 L444 846 L290 748 L150 774 Z",
                "M930 730 L850 584 L670 652 L630 690 L500 820 L556 846 L710 748 L850 774 Z"]
    out = f'<g clip-path="url(#body)">{body}</g>'
    for d in laps:
        out += f'<path d="{d}" fill="{KHAKI_L}" {S}/>'
    out += f'<path d="M160 612 L280 712 M840 612 L720 712" stroke="{KHAKI_D}" stroke-width="8" stroke-linecap="round"/>'
    # the body outline again on top, so the coat edge never looks pasted on
    out += f'<path d="{FILL_D}" fill="none" stroke="#000" stroke-width="3"/>'
    return out


def packets():
    """Seed packets pinned inside the open coat."""
    out = ""
    for (x, y, n, rot, col) in [(352, 712, "4", -6, ACCENT), (500, 720, "13", 3, "#7fb7ff"), (648, 712, "30", 7, MINT)]:
        out += (f'<g transform="translate({x} {y}) rotate({rot})">'
                f'<rect x="-66" y="0" width="132" height="168" rx="6" fill="{PAPER}" {S10}/>'
                f'<rect x="-66" y="0" width="132" height="44" rx="6" fill="{col}" {S10}/>'
                f'<text x="0" y="32" {FONT} font-size="30" text-anchor="middle" fill="#000">SEED</text>'
                f'<text x="0" y="130" {FONT} font-size="{80 if len(n) == 1 else 70}" text-anchor="middle" fill="#000">{n}</text>'
                f'<circle cx="0" cy="-6" r="9" fill="{GREY}" stroke="#000" stroke-width="6"/></g>')
    return out


def fedora():
    out = '<g transform="rotate(-7 500 160)">'
    # crown with a pinch, then band, then brim on top so the brim edge reads in front
    out += f'<path d="M346 166 C340 110 350 50 392 34 C430 22 470 46 500 46 C530 46 570 22 608 34 C650 50 660 110 654 166 Z" fill="{HAT}" {S}/>'
    out += f'<path d="M500 52 C496 80 498 110 502 140" fill="none" stroke="{HAT_D}" stroke-width="10" stroke-linecap="round"/>'
    out += f'<path d="M344 126 C420 140 580 140 656 126 L656 166 L344 166 Z" fill="{HAT_D}" stroke="#000" stroke-width="12" stroke-linejoin="round"/>'
    out += seed(620, 112, 0.62, 28)
    out += f'<path d="M262 178 C300 140 700 140 738 178 C750 196 720 206 690 198 C600 176 400 176 310 198 C280 206 250 196 262 178 Z" fill="{HAT}" {S}/>'
    return out + '</g>'


def shades():
    out = ""
    for d in EYE_D:
        out += f'<path d="{d}" fill="#15151f" opacity="0.88"/>'
    # glints
    out += ('<path d="M200 470 L250 450 M206 500 L300 462 M645 470 L695 450 M651 500 L745 462" '
            'stroke="#fff" stroke-width="12" stroke-linecap="round" opacity="0.85"/>')
    return out


def smirk():
    # a sly half-smile and a toothpick hanging off the corner
    return ('<path d="M466 640 C490 650 522 650 548 630" fill="none" stroke="#000" stroke-width="12" stroke-linecap="round"/>'
            f'<path d="M548 632 L640 670" stroke="#000" stroke-width="18" stroke-linecap="round"/>'
            f'<path d="M548 632 L640 670" stroke="{TAN}" stroke-width="8" stroke-linecap="round"/>')


def kun(open_=False):
    face = "".join(FACE)
    return (f'<g id="kun">{OUTLINE}{FILL}{coat(open_)}{packets() if open_ else ""}{face}'
            f'{shades()}{smirk()}{fedora()}</g>')


# --- props (centred on 0,0, about +-150) ------------------------------------------------------------

MINT = "#9fe0c8"


def die(x, y, rot, pips):
    pos = {1: [(0, 0)], 2: [(-26, -26), (26, 26)], 3: [(-26, -26), (0, 0), (26, 26)],
           4: [(-26, -26), (26, -26), (-26, 26), (26, 26)],
           5: [(-26, -26), (26, -26), (0, 0), (-26, 26), (26, 26)],
           6: [(-26, -28), (26, -28), (-26, 0), (26, 0), (-26, 28), (26, 28)]}[pips]
    d = "".join(f'<circle cx="{px}" cy="{py}" r="11" fill="#000"/>' for px, py in pos)
    return (f'<g transform="translate({x} {y}) rotate({rot})"><rect x="-62" y="-62" width="124" height="124" rx="22" '
            f'fill="#fff" {S}/>{d}</g>')


PROP = {}
PROP["dice"] = f'''<g>{die(-60, 30, -14, 4)}{die(70, -20, 18, 6)}
</g>'''

PROP["magnifier"] = f'''<g transform="rotate(-20)">
   <path d="M60 60 L150 150" stroke="#000" stroke-width="56" stroke-linecap="round"/>
   <path d="M66 66 L146 146" stroke="{HAT}" stroke-width="34" stroke-linecap="round"/>
   <circle r="112" fill="#dff1ff" {S}/>
   <path d="M-80 30 L-40 30 L-20 -30 L20 -30 L36 40 L76 40" fill="none" stroke="{RED}" stroke-width="14" stroke-linejoin="round" stroke-linecap="round"/>
   <circle cx="-80" cy="30" r="12" fill="#000"/><circle cx="76" cy="40" r="12" fill="#000"/>
   <path d="M-60 -70 C-40 -86 -16 -92 4 -90" fill="none" stroke="#fff" stroke-width="14" stroke-linecap="round"/>
   <circle r="112" fill="none" stroke="#000" stroke-width="22"/>
   <circle r="112" fill="none" stroke="{ACCENT}" stroke-width="10"/>
 </g>'''

PROP["stopwatch"] = f'''<g>
   <rect x="-26" y="-170" width="52" height="34" rx="8" fill="{ACCENT}" {S10}/>
   <path d="M-6 -136 L-6 -120 M6 -136 L6 -120" stroke="#000" stroke-width="10"/>
   <path d="M96 -98 L122 -124" stroke="#000" stroke-width="22" stroke-linecap="round"/>
   <circle r="130" fill="#fff" {S}/>
   <circle r="104" fill="none" stroke="{GREY}" stroke-width="6"/>
   <path d="M0 -104 L0 -84 M104 0 L84 0 M0 104 L0 84 M-104 0 L-84 0" stroke="#000" stroke-width="10" stroke-linecap="round"/>
   <path d="M0 0 L0 -104 A104 104 0 0 1 60 -85 Z" fill="{RED}" opacity="0.35"/>
   <path d="M0 0 L58 -84" stroke="{RED}" stroke-width="12" stroke-linecap="round"/>
   <path d="M0 0 L-40 30" stroke="#000" stroke-width="12" stroke-linecap="round"/>
   <circle r="14" fill="#000"/>
 </g>'''

PROP["receipt"] = f'''<g transform="rotate(8)">
   <path d="M-96 -170 L96 -170 L96 150 L80 166 L64 150 L48 166 L32 150 L16 166 L0 150 L-16 166 L-32 150 L-48 166 L-64 150 L-80 166 L-96 150 Z" fill="{PAPER}" {S}/>
   <text x="0" y="-126" {FONT} font-size="30" text-anchor="middle" fill="#000">SLACK</text>
   <path d="M-70 -100 L70 -100 M-70 -70 L30 -70 M-70 -40 L50 -40" stroke="{GREY}" stroke-width="10" stroke-linecap="round"/>
   <text x="0" y="40" {FONT} font-size="50" text-anchor="middle" fill="{RED}">-0.469</text>
   <text x="0" y="88" {FONT} font-size="34" text-anchor="middle" fill="{RED}">ns</text>
   <path d="M-70 116 L70 116" stroke="#000" stroke-width="8" stroke-dasharray="14 10"/>
 </g>'''

PROP["ticket"] = f'''<g transform="rotate(-14)">
   <path d="M-160 -80 L160 -80 L160 -30 A30 30 0 0 0 160 30 L160 80 L-160 80 L-160 30 A30 30 0 0 0 -160 -30 Z" fill="{GREEN}" {S}/>
   <path d="M-104 -60 L-104 60" stroke="#000" stroke-width="8" stroke-dasharray="12 10"/>
   <text x="-132" y="12" {FONT} font-size="40" text-anchor="middle" fill="#fff" transform="rotate(-90 -132 0)">ADMIT</text>
   <text x="28" y="-8" {FONT} font-size="52" text-anchor="middle" fill="#fff" stroke="#000" stroke-width="8" paint-order="stroke">TIMING</text>
   <text x="28" y="54" {FONT} font-size="58" text-anchor="middle" fill="#fff" stroke="#000" stroke-width="8" paint-order="stroke">MET</text>
 </g>'''

PROP["chip"] = f'''<g transform="rotate(-10)">
   {"".join(f'<path d="M{x} -150 L{x} -110 M{x} 150 L{x} 110 M-150 {x} L-110 {x} M150 {x} L110 {x}" stroke="#000" stroke-width="26" stroke-linecap="round"/><path d="M{x} -148 L{x} -110 M{x} 148 L{x} 110 M-148 {x} L-110 {x} M148 {x} L110 {x}" stroke="{GREY}" stroke-width="12" stroke-linecap="round"/>' for x in (-70, -24, 24, 70))}
   <rect x="-118" y="-118" width="236" height="236" rx="18" fill="#2b2b3a" {S}/>
   <circle cx="-80" cy="-80" r="10" fill="{GREY}"/>
   <text x="0" y="-8" {FONT} font-size="50" text-anchor="middle" fill="#fff">FPGA</text>
   <text x="0" y="52" {FONT} font-size="34" text-anchor="middle" fill="{ACCENT}">CYCLONE V</text>
 </g>'''

PROP["sprout"] = f'''<g>
   <path d="M0 -10 C-4 -60 4 -100 0 -140" fill="none" stroke="#000" stroke-width="24" stroke-linecap="round"/>
   <path d="M0 -10 C-4 -60 4 -100 0 -140" fill="none" stroke="{GREEN}" stroke-width="12" stroke-linecap="round"/>
   <path d="M0 -120 C-30 -170 -100 -170 -120 -140 C-90 -100 -30 -100 0 -120 Z" fill="{GREEN}" {S10}/>
   <path d="M0 -100 C30 -150 100 -160 124 -126 C96 -84 36 -80 0 -100 Z" fill="{GREEN}" {S10}/>
   <path d="M-16 -124 C-50 -136 -80 -138 -100 -134 M16 -104 C50 -118 80 -122 104 -122" fill="none" stroke="{GREEN_D}" stroke-width="7" stroke-linecap="round"/>
   <path d="M-110 -10 L110 -10 L84 150 L-84 150 Z" fill="{POT}" {S}/>
   <rect x="-126" y="-30" width="252" height="50" rx="10" fill="{POT}" {S}/>
   <text x="0" y="96" {FONT} font-size="44" text-anchor="middle" fill="#fff" stroke="#000" stroke-width="8" paint-order="stroke">SEED 4</text>
 </g>'''

PROP["packet"] = f'''<g transform="rotate(10)">
   <rect x="-100" y="-140" width="200" height="270" rx="8" fill="{PAPER}" {S}/>
   <rect x="-100" y="-140" width="200" height="70" rx="8" fill="{ACCENT}" {S}/>
   <text x="0" y="-90" {FONT} font-size="48" text-anchor="middle" fill="#000">SEED</text>
   {seed(-44, 10, 0.9, -20)}{seed(40, 30, 0.9, 25)}
   <text x="0" y="112" {FONT} font-size="38" text-anchor="middle" fill="#000">No. 4</text>
 </g>'''

ICON_ONLY = {
    "fedora": f'<g transform="translate(-500 -110) scale(1)">{fedora()}</g>',
    "shades": (f'<g transform="translate(-500 -500)"><path d="M146 410 L880 410 L880 450 L146 450 Z" fill="#000"/>'
               + "".join(f'<path d="{d}" fill="#000" stroke="#000" stroke-width="16"/>' for d in EYE_D) + shades() + '</g>'),
    "seed": seed(0, 0, 2.2, 20),
}


def with_prop(name, x=870, y=840, s=1.1, open_=False):
    return DEFS + kun(open_) + f'<g transform="translate({x} {y}) scale({s})">{PROP[name]}</g>'


# --- output helpers (same as the Tasty pipeline) ------------------------------------------------------

def svg(w, h, body, vb=None, bg=None):
    vb = vb or f"0 0 {w} {h}"
    b = f'<rect x="-10000" y="-10000" width="20000" height="20000" fill="{bg}"/>' if bg else ""
    return f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="{vb}">{b}{body}</svg>'


def write(name, text, d=ART):
    p = os.path.join(d, name + ".svg")
    open(p, "w").write(text)
    return p


def png(svgp, w, pngname=None, d=ART):
    pn = os.path.join(d, (pngname or os.path.basename(svgp)[:-4]) + ".png")
    subprocess.run(["inkscape", svgp, "--export-type=png", f"--export-filename={pn}", f"--export-width={w}"],
                   check=True, capture_output=True)
    return pn


def nested(inner, x, y, size, vb="0 0 1000 1000"):
    return f'<svg x="{x}" y="{y}" width="{size}" height="{size}" viewBox="{vb}">{inner}</svg>'


def wordmark(x, y, scale=1.0, jp=True, dark=False):
    ink = "#f0efef" if dark else "#000"
    t = f'<g transform="translate({x} {y}) scale({scale})">'
    t += f'<text x="0" y="0" {FONT} font-size="120" fill="{ink}" letter-spacing="-2">MiSTer</text>'
    t += (f'<text x="0" y="150" {FONT} font-size="170" fill="{ACCENT}" stroke="{ink}" stroke-width="10" '
          f'paint-order="stroke" letter-spacing="4">SEEDY</text>')
    if jp:
        t += f'<text x="8" y="235" {JP} font-size="62" fill="{ink}">ミスター・シーディー</text>'
    return t + '</g>'


def props_row(x, y, size, gap, names):
    out = ""
    for i, n in enumerate(names):
        out += f'<g transform="translate({x + i * (size + gap) + size / 2} {y + size / 2}) scale({size / 340})">{PROP[n]}</g>'
    return out


TAGLINE = "Shady seeds. Honest statistics."
VARIANTS = ["packet", "dice", "magnifier", "stopwatch", "receipt", "ticket", "chip", "sprout"]
VB = "-20 -20 1120 1120"   # room for the hat brim and the prop


def main():
    os.makedirs(ICONS, exist_ok=True)
    made = []
    p = write("seedy-kun", svg(1000, 1000, DEFS + kun(), vb="-10 -10 1020 1020")); made.append(png(p, 512))
    # coat flung open, with a speech bubble
    bubble = (f'<g transform="translate(905 150)"><path d="M-150 -70 L150 -70 C170 -70 180 -60 180 -40 L180 40 C180 60 170 70 150 70 '
              f'L-40 70 L-110 120 L-90 70 L-150 70 C-170 70 -180 60 -180 40 L-180 -40 C-180 -60 -170 -70 -150 -70 Z" fill="#fff" {S}/>'
              f'<text x="0" y="22" {FONT} font-size="64" text-anchor="middle" fill="#000">psst...</text></g>')
    p = write("seedy-kun-open", svg(1080, 1080, DEFS + kun(open_=True) + bubble, vb=VB)); made.append(png(p, 512))
    for v in VARIANTS:
        p = write(f"seedy-kun-{v}", svg(1080, 1080, with_prop(v), vb=VB)); made.append(png(p, 512))

    # social preview 1280x640
    body = nested(DEFS + kun(open_=True), 50, 60, 520, vb="-20 -20 1040 1040")
    body += wordmark(610, 210, 1.0)
    body += f'<text x="616" y="520" {FONT} font-size="40" fill="#000">{TAGLINE}</text>'
    body += "".join(f'<rect x="{616 + i * 150}" y="560" width="150" height="28" fill="{c}"/>'
                    for i, c in enumerate([ACCENT, KHAKI, "#000", GREY]))
    p = write("social-preview", svg(1280, 640, body, bg="#ffffff")); made.append(png(p, 1280))

    # README banner 1280x420, dark
    body = nested(DEFS + kun(), 50, 30, 360, vb="-10 -10 1020 1020")
    body += wordmark(452, 150, 0.72, jp=False, dark=True)
    body += f'<text x="458" y="326" {JP} font-size="40" fill="#f0efef">ミスター・シーディー</text>'
    body += props_row(892, 96, 62, 12, ["packet", "dice", "magnifier", "stopwatch", "sprout"])
    body += f'<text x="894" y="262" {FONT} font-size="30" fill="#f0efef">Shady seeds.</text>'
    body += f'<text x="894" y="304" {FONT} font-size="30" fill="#f0efef">Honest statistics for</text>'
    body += f'<text x="894" y="346" {FONT} font-size="30" fill="{ACCENT}">MiSTer core timing.</text>'
    p = write("banner", svg(1280, 420, body, bg="#16162e")); made.append(png(p, 1280))

    # heading icons
    tmp = os.path.join(HERE, "out-scratch")
    os.makedirs(tmp, exist_ok=True)
    icons = dict(PROP)
    icons.update(ICON_ONLY)
    for name, g in icons.items():
        sc = {"fedora": 0.98, "shades": 0.5, "seed": 1.0}.get(name, 1.3)
        body = DEFS + f'<g transform="translate(250 270) scale({sc})">{g}</g>'
        p = write(f"icon-{name}", svg(500, 540, body), d=tmp)
        made.append(png(p, 48, f"{name}-48", d=ICONS))
    print("\n".join(made))


# --- 8-bit Seedy Kun: the upstream 32x32 pixel Kun, repainted by hand -------------------------------

KUN8 = """\
.........K............K.........
........KWK..........KWK........
.......KWKWK........KWKWK.......
......KWKGKWK......KWKGKWK......
.....KWKKKKKWKKKKKKWKKKKKWK.....
....KWWWWWWWWWWWWWWWWWWWWWWK....
....KWWWWWWWWWWWWWWWWWWWWWWK....
...KWWWWWWWWWWWWWWWWWWWWWWWWK...
...KWWWWWWWWWWWWWWWWWWWWWWWWK...
...KWWWWWWWWWWWWWWWWWWWWWWWWK...
...KWWWWWWWWWWWWWWWWWWWWWWWWK...
...KWWWWWWWWWKWWWWKWWWWWWWWWK...
...KWKKKKKKKKKKKKKKKKKKKKKKWK...
...KWKWWWKKKKWKPPKWKKKKWWWKWK...
..KKWKWWWWKKWWKPPKWWKKWWWWKWKK..
.KWWWKWWWWWWWWKKKKWWWWWWWWKWWWK.
.KWWWWKWWWWWWKKRRKKWWWWWWKWWWWK.
KWWWWWWKKKKKKPPKKPPKKKKKKWWWWWWK
KWWWWWWWWWWKPPPPPPPPKWWWWWWWWWWK
KWWWWWWWWWWWKPPKKPPKWWWWWWWWWWWK
.KWWWWWWWWWKWKKPPKKWKWWWWWWWWWK.
.KWWWWWWWWWKWWWKKWWWKWWWWWWWWWK.
..KKWWWWWWWWWWWWWWWWWWWWWWWWKK..
...KWWWWWWWWWWWWWWWWWWWWWWWWK...
...KWWWWWWWWWWWWWWWWWWWWWWWWK...
...KWWWWWWWWWWWWWWWWWWWWWWWWK...
..KWWWWWWWWWWWKKKKWWWWWWWWWWWK..
.KWWWWWWWWWWWK....KWWWWWWWWWWWK.
.KWWWWWWWWWWK......KWWWWWWWWWWK.
..KWWWWWWWWWK......KWWWWWWWWWK..
...KKKKKKKKK........KKKKKKKKK...
"""
PAL8 = {"K": "#010101", "W": "#f0efef", "G": "#e98db8", "P": "#b4b4b4", "R": "#e177af", "H": HAT, "D": HAT_D,
        "S": "#2a2a3a", "w": "#ffffff", "C": KHAKI, "c": KHAKI_D, "L": KHAKI_L, "T": LINING, "Y": ACCENT, "O": TAN}


def kun8():
    g = [list(r) for r in KUN8.splitlines()]
    g.insert(0, list("." * 32))   # the file starts one row down, like the upstream grid
    def put(x, y, c):
        g[y][x] = c
    # shades: fill both eye areas dark, one glint each
    for y in range(14, 18):
        for x in range(4, 28):
            if g[y][x] == "W" and 5 <= x <= 13 or g[y][x] == "W" and 18 <= x <= 26:
                if y < 17 or 7 <= x <= 12 or 19 <= x <= 24:
                    put(x, y, "S")
    put(7, 14, "w"); put(20, 14, "w")
    # fedora: crown, band, brim
    for x in range(11, 21):
        put(x, 1, "K")
    for y in (2, 3):
        put(10, y, "K"); put(21, y, "K")
        for x in range(11, 21):
            put(x, y, "H")
    put(10, 4, "K"); put(21, 4, "K")
    for x in range(11, 21):
        put(x, 4, "D")
    put(19, 3, "Y")   # a seed in the hat band
    put(7, 5, "K"); put(24, 5, "K")
    for x in range(8, 24):
        put(x, 5, "H")
    for x in range(8, 24):
        put(x, 6, "K")
    # toothpick
    put(21, 21, "O"); put(22, 22, "O")
    # trenchcoat over rows 23..30, V neck with a tie, belt and buckle
    for y in range(23, 31):
        for x in range(32):
            if g[y][x] == "W":
                put(x, y, "C")
    for y, (a, b) in zip(range(23, 26), [(12, 19), (13, 18), (14, 17)]):
        for x in range(a, b + 1):
            put(x, y, "W")
    for y in (23, 24, 25):
        put(15, y, "T"); put(16, y, "T")
    for x, y in [(11, 23), (12, 24), (13, 25), (14, 26), (20, 23), (19, 24), (18, 25), (17, 26),
                 (10, 23), (11, 24), (12, 25), (21, 23), (20, 24), (19, 25)]:
        put(x, y, "L")
    for x in range(32):
        if g[27][x] == "C":
            put(x, 27, "c")
    for x in (4, 5, 6):
        put(x, 23, "L")
    for x in (25, 26, 27):
        put(x, 23, "L")
    rects = "".join(f'<rect x="{x}" y="{y}" width="1" height="1" fill="{PAL8[c]}"/>'
                    for y, row in enumerate(g) for x, c in enumerate(row) if c != ".")
    return f'<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 32 32" shape-rendering="crispEdges">{rects}</svg>'


def main8():
    p = write("seedy-kun-8bit-32x32", kun8())
    png(p, 32)
    print(png(p, 512, "seedy-kun-8bit"))


if __name__ == "__main__":
    main()
    main8()
