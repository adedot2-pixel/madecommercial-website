"""Rebuilds the MADE Commercial logo as a clean vector with TRUE transparency.

The source SVG is a trace: navy/green shapes plus separate white shapes drawn on top to fake the
letter interiors. This replays the shapes in paint order with boolean path operations, so white
shapes become real holes. Output uses only two filled paths (navy, green) and no white at all.

Run with the helper env:  vlogo/bin/python tools/rebuild_logo.py <source.svg> <out_dir>
(needs skia-pathops and fonttools)"""
import re, sys, math, os
import xml.etree.ElementTree as ET
import pathops
from pathops import Path, PathOp, FillType
from fontTools.svgLib.path import parse_path
from fontTools.pens.transformPen import TransformPen
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.misc.transform import Transform

NS = '{http://www.w3.org/2000/svg}'
src, outdir = sys.argv[1], sys.argv[2]
os.makedirs(outdir, exist_ok=True)

def parse_transform(t):
    m = Transform()
    for name, args in re.findall(r'(\w+)\(([^)]*)\)', t or ''):
        a = [float(x) for x in re.split(r'[ ,]+', args.strip())]
        if name == 'translate': m = m.translate(a[0], a[1] if len(a) > 1 else 0)
        elif name == 'rotate': m = m.rotate(math.radians(a[0]))
        elif name == 'scale': m = m.scale(a[0], a[1] if len(a) > 1 else a[0])
        elif name == 'matrix': m = m.transform(a)
    return m

K = 0.5522847498
def ellipse_to_pen(pen, rx, ry):
    pen.moveTo((rx, 0))
    pen.curveTo((rx, K*ry), (K*rx, ry), (0, ry))
    pen.curveTo((-K*rx, ry), (-rx, K*ry), (-rx, 0))
    pen.curveTo((-rx, -K*ry), (-K*rx, -ry), (0, -ry))
    pen.curveTo((K*rx, -ry), (rx, -K*ry), (rx, 0))
    pen.closePath()

def shape_path(el):
    p = Path(); pen = p.getPen()
    tag = el.tag.replace(NS, '')
    tf = parse_transform(el.get('transform'))
    tpen = TransformPen(pen, tf)
    if tag == 'path':
        parse_path(el.get('d'), tpen)
    elif tag == 'rect':
        x, y, w, h = (float(el.get(k)) for k in ('x', 'y', 'width', 'height'))
        tpen.moveTo((x, y)); tpen.lineTo((x+w, y)); tpen.lineTo((x+w, y+h)); tpen.lineTo((x, y+h)); tpen.closePath()
    elif tag == 'ellipse':
        t2 = tf.translate(float(el.get('cx')), float(el.get('cy')))
        ellipse_to_pen(TransformPen(pen, t2), float(el.get('rx')), float(el.get('ry')))
    else:
        return None
    p.fillType = FillType.WINDING
    return pathops.simplify(p, fix_winding=True)

def bounds_w(p):
    b = p.bounds
    return b[2] - b[0]

root = ET.parse(src).getroot()
acc = {'navy': Path(), 'green': Path()}
colour = {'#15283c': 'navy', '#537953': 'green', '#ffffff': 'white'}
n = {'navy': 0, 'green': 0, 'white': 0, 'skipped': 0}
for el in root.iter():
    tag = el.tag.replace(NS, '')
    if tag not in ('path', 'rect', 'ellipse'): continue
    fill = (el.get('fill') or '').lower()
    if fill not in colour: n['skipped'] += 1; continue   # strokes / debug outlines
    p = shape_path(el)
    if p is None or not len(list(p.segments)): continue
    c = colour[fill]
    if c == 'white' and bounds_w(p) > 1000: n['skipped'] += 1; continue   # full-canvas white frame
    n[c] += 1
    for other in acc:
        if other != c:
            acc[other] = pathops.op(acc[other], p, PathOp.DIFFERENCE, fix_winding=True)
    if c != 'white':
        acc[c] = pathops.op(acc[c], p, PathOp.UNION, fix_winding=True)
print('shapes replayed:', n)

def d_of(p, tx=0, ty=0):
    pen = SVGPathPen(None, ntos=lambda v: ('%.2f' % v).rstrip('0').rstrip('.'))
    p.draw(TransformPen(pen, Transform().translate(tx, ty)))
    return pen.getCommands()

def svg(viewbox, navy, green, tagline=True):
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="%s" role="img" aria-label="MADE Commercial">'
            '<path fill="%s" fill-rule="nonzero" d="%s"/><path fill="%s" fill-rule="nonzero" d="%s"/></svg>\n'
            % (viewbox, navy[0], d_of(acc['navy']), green[0], d_of(acc['green'])))

BRAND = {'navy': '#16263F', 'green': '#4E7F54'}
variants = {
    'logo.svg':            ('225 245 1090 520', BRAND['navy'], BRAND['green']),   # with tagline
    'logo-mark.svg':       ('225 245 1090 370', BRAND['navy'], BRAND['green']),   # wordmark only
    'logo-white.svg':      ('225 245 1090 520', '#FFFFFF', '#9FC7A4'),            # for dark backgrounds
    'logo-mark-white.svg': ('225 245 1090 370', '#FFFFFF', '#9FC7A4'),
}
for name, (vb, nv, gr) in variants.items():
    with open(os.path.join(outdir, name), 'w') as f:
        f.write(svg(vb, (nv,), (gr,)))
    print('wrote', name)
