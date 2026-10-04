"""Generates the site's brand imagery as SVG (navy / green duotone, with reflections).
Run: python3 tools/gen_images.py"""
import random, math, os
OUT = os.path.join(os.path.dirname(__file__), '..', 'public', 'assets', 'img')
NAVY, NAVY2, MID, STEEL, LIGHT, GREEN, GLIGHT = '#16263F', '#1d3355', '#2e4a73', '#6b84a8', '#dfe7f1', '#4E7F54', '#9fc7a4'

def save(name, svg):
    with open(os.path.join(OUT, name), 'w') as f: f.write(svg)

def tower(x, y, w, h, gid, rnd, floors=26, lit=0.10):
    """A glass tower with specular edge, floor lines and a few lit windows."""
    s = [f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="url(#{gid})"/>']
    step = h / floors
    for i in range(1, floors):
        s.append(f'<rect x="{x}" y="{y+i*step:.1f}" width="{w}" height="1" fill="#fff" opacity="0.07"/>')
    cols = max(2, int(w // 22))
    for i in range(floors):
        for c in range(cols):
            if rnd.random() < lit:
                wx = x + 6 + c * (w - 12) / cols
                col = GLIGHT if rnd.random() < 0.35 else '#fff'
                s.append(f'<rect x="{wx:.1f}" y="{y+i*step+4:.1f}" width="{(w-12)/cols-5:.1f}" height="{step-8:.1f}" fill="{col}" opacity="{rnd.uniform(.25,.6):.2f}"/>')
    s.append(f'<rect x="{x}" y="{y}" width="1.6" height="{h}" fill="#fff" opacity="0.38"/>')            # specular left edge
    s.append(f'<rect x="{x+w-1}" y="{y}" width="1" height="{h}" fill="#000" opacity="0.25"/>')
    return '\n'.join(s)

def hero():
    rnd = random.Random(7)
    W, H, FLOOR = 1200, 900, 640
    g = [f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" role="img" aria-label="Abstract glass towers rising like a bar chart, reflected in a polished floor">
<defs>
<linearGradient id="bg" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{NAVY}"/><stop offset="1" stop-color="{NAVY2}"/></linearGradient>
<linearGradient id="glass" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#4a6a9c"/><stop offset=".18" stop-color="{MID}"/><stop offset=".7" stop-color="#1a2e50"/><stop offset="1" stop-color="#12203a"/></linearGradient>
<linearGradient id="glassG" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#7fb486"/><stop offset=".2" stop-color="{GREEN}"/><stop offset="1" stop-color="#2f5535"/></linearGradient>
<linearGradient id="floor" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#2a4670"/><stop offset="1" stop-color="{NAVY}"/></linearGradient>
<linearGradient id="fade" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#fff" stop-opacity=".42"/><stop offset=".75" stop-color="#fff" stop-opacity="0"/></linearGradient>
<mask id="rm"><rect x="0" y="{FLOOR}" width="{W}" height="{H-FLOOR}" fill="url(#fade)"/></mask>
<radialGradient id="glow" cx=".72" cy=".42" r=".6"><stop offset="0" stop-color="{GREEN}" stop-opacity=".35"/><stop offset="1" stop-color="{GREEN}" stop-opacity="0"/></radialGradient>
<linearGradient id="glare" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#fff" stop-opacity="0"/><stop offset=".5" stop-color="#fff" stop-opacity=".13"/><stop offset="1" stop-color="#fff" stop-opacity="0"/></linearGradient>
<clipPath id="towersClip"><rect x="0" y="0" width="{W}" height="{FLOOR}"/></clipPath>
</defs>
<rect width="{W}" height="{H}" fill="url(#glow)"/>
<g id="scene">''']
    # five rising towers echoing the logo bars + supporting low-rise
    specs = [(110, 200, 120), (260, 270, 140), (430, 350, 150), (620, 440, 160), (830, 530, 170)]
    back = [(40, 120, 90), (200, 170, 80), (370, 230, 90), (560, 280, 80), (760, 330, 90), (1010, 250, 110)]
    for x, h, w in back:   # background, dimmer
        g.append(f'<g opacity=".45">{tower(x, FLOOR-h, w, h, "glass", rnd, floors=18, lit=.05)}</g>')
    for i, (x, h, w) in enumerate(specs):
        gid = 'glassG' if i == 4 else 'glass'
        g.append(tower(x, FLOOR-h, w, h, gid, rnd, floors=int(h/24), lit=.12))
    g.append(f'<polygon points="520,{FLOOR} 760,{FLOOR} 1060,0 760,0" fill="url(#glare)" clip-path="url(#towersClip)"/>')
    g.append('</g>')
    g.append(f'<rect x="0" y="{FLOOR}" width="{W}" height="{H-FLOOR}" fill="url(#floor)"/>')
    g.append(f'<rect x="0" y="{FLOOR}" width="{W}" height="2" fill="#fff" opacity=".25"/>')
    g.append(f'<g mask="url(#rm)"><use href="#scene" transform="translate(0,{2*FLOOR}) scale(1,-1)"/></g>')
    g.append('</svg>')
    save('hero.svg', '\n'.join(g))

def sky_defs(prefix, top, bottom):
    return f'<linearGradient id="{prefix}sky" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{top}"/><stop offset="1" stop-color="{bottom}"/></linearGradient>'

def fm():
    rnd = random.Random(3)
    W, H = 800, 1000
    s = [f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" role="img" aria-label="Abstract building facade">
<defs>
<linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="{MID}"/><stop offset="1" stop-color="{NAVY}"/></linearGradient>
<linearGradient id="gl" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#fff" stop-opacity="0"/><stop offset=".5" stop-color="#fff" stop-opacity=".16"/><stop offset="1" stop-color="#fff" stop-opacity="0"/></linearGradient>
</defs>
<rect width="{W}" height="{H}" fill="url(#bg)"/>''']
    cols, rows, pad = 6, 11, 40
    cw, rh = (W - 2*pad) / cols, (H - 2*pad) / rows
    for r in range(rows):
        for c in range(cols):
            x, y = pad + c*cw, pad + r*rh
            lit = rnd.random()
            fill = GLIGHT if lit > .93 else ('#fff' if lit > .72 else '#0e1a2e')
            op = .55 if lit > .93 else (.22 if lit > .72 else .55)
            s.append(f'<rect x="{x+6:.1f}" y="{y+6:.1f}" width="{cw-12:.1f}" height="{rh-12:.1f}" rx="2" fill="{fill}" opacity="{op}"/>')
            s.append(f'<rect x="{x+6:.1f}" y="{y+6:.1f}" width="{cw-12:.1f}" height="1.5" fill="#fff" opacity=".35"/>')
    # accent green mullion + glare
    s.append(f'<rect x="{pad+2*cw-3:.1f}" y="{pad}" width="6" height="{H-2*pad}" fill="{GREEN}" opacity=".9"/>')
    s.append(f'<polygon points="120,0 360,0 700,{H} 460,{H}" fill="url(#gl)"/>')
    s.append('</svg>')
    save('sector-fm.svg', '\n'.join(s))

def subsea():
    rnd = random.Random(11)
    W, H, WL = 800, 1000, 430
    s = [f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" role="img" aria-label="Abstract subsea cable crossing the ocean floor">
<defs>
<linearGradient id="sky" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#2e4a73"/><stop offset="1" stop-color="#9db4d2"/></linearGradient>
<linearGradient id="sea" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#2a4a78"/><stop offset=".45" stop-color="#16263F"/><stop offset="1" stop-color="#0c1628"/></linearGradient>
<linearGradient id="ray" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#fff" stop-opacity=".18"/><stop offset="1" stop-color="#fff" stop-opacity="0"/></linearGradient>
</defs>
<rect width="{W}" height="{WL}" fill="url(#sky)"/>
<rect y="{WL}" width="{W}" height="{H-WL}" fill="url(#sea)"/>''']
    for x0 in (120, 330, 520, 690):
        s.append(f'<polygon points="{x0},{WL} {x0+60},{WL} {x0+190},{H} {x0-70},{H}" fill="url(#ray)" opacity=".5"/>')
    # ship + reflection
    ship = f'<g><path d="M250,{WL-4} L560,{WL-4} L530,{WL-30} L290,{WL-30} Z" fill="#0e1a2e"/><rect x="340" y="{WL-62}" width="90" height="32" fill="#0e1a2e"/><rect x="450" y="{WL-92}" width="6" height="62" fill="#0e1a2e"/><rect x="352" y="{WL-52}" width="66" height="8" fill="{GLIGHT}" opacity=".6"/></g>'
    s.append(ship)
    s.append(f'<g opacity=".25" transform="translate(0,{2*WL}) scale(1,-1)">{ship}</g>')
    s.append(f'<rect y="{WL}" width="{W}" height="2" fill="#fff" opacity=".35"/>')
    # waves
    for i in range(9):
        y = WL + 14 + i*9
        s.append(f'<path d="M0,{y} q 40,-6 80,0 t 80,0 t 80,0 t 80,0 t 80,0 t 80,0 t 80,0 t 80,0 t 80,0 t 80,0" fill="none" stroke="#fff" stroke-opacity="{.16-i*.015:.3f}" stroke-width="1.2"/>')
    # seabed
    seabed = f'M0,{H-120} C140,{H-170} 260,{H-90} 400,{H-130} S650,{H-190} 800,{H-110} L800,{H} L0,{H} Z'
    s.append(f'<path d="{seabed}" fill="#0a1424"/>')
    s.append(f'<path d="M0,{H-120} C140,{H-170} 260,{H-90} 400,{H-130} S650,{H-190} 800,{H-110}" fill="none" stroke="#fff" stroke-opacity=".12"/>')
    # cable + repeaters
    cable = f'M410,{WL-6} C410,{WL+200} 220,{WL+260} 200,{H-230} S 380,{H-150} 520,{H-150} S 720,{H-165} 800,{H-165}'
    s.append(f'<path d="{cable}" fill="none" stroke="{GLIGHT}" stroke-width="3" stroke-linecap="round"/>')
    s.append(f'<path d="{cable}" fill="none" stroke="#fff" stroke-width="1" stroke-opacity=".6" stroke-linecap="round" transform="translate(-1,-1)"/>')
    for (cx, cy) in [(236, H-330), (330, H-175), (560, H-153), (720, H-165)]:
        s.append(f'<circle cx="{cx}" cy="{cy}" r="9" fill="{NAVY}" stroke="{GLIGHT}" stroke-width="2"/><circle cx="{cx}" cy="{cy}" r="3" fill="{GLIGHT}"/>')
    for _ in range(28):
        s.append(f'<circle cx="{rnd.randint(0,W)}" cy="{rnd.randint(WL+30,H-200)}" r="{rnd.uniform(.8,2):.1f}" fill="#fff" opacity="{rnd.uniform(.1,.4):.2f}"/>')
    s.append('</svg>')
    save('sector-subsea.svg', '\n'.join(s))

def life():
    rnd = random.Random(5)
    W, H = 800, 1000
    s = [f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" role="img" aria-label="Abstract molecular network">
<defs>
<linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#1d3355"/><stop offset="1" stop-color="{NAVY}"/></linearGradient>
<radialGradient id="n" cx=".35" cy=".3" r=".8"><stop offset="0" stop-color="#fff"/><stop offset=".35" stop-color="{GLIGHT}"/><stop offset="1" stop-color="{GREEN}"/></radialGradient>
<radialGradient id="nb" cx=".35" cy=".3" r=".8"><stop offset="0" stop-color="#fff"/><stop offset=".4" stop-color="#9db4d2"/><stop offset="1" stop-color="{MID}"/></radialGradient>
<radialGradient id="glow" cx=".5" cy=".45" r=".6"><stop offset="0" stop-color="{GREEN}" stop-opacity=".3"/><stop offset="1" stop-color="{GREEN}" stop-opacity="0"/></radialGradient>
</defs>
<rect width="{W}" height="{H}" fill="url(#bg)"/><rect width="{W}" height="{H}" fill="url(#glow)"/>''']
    # faint hex grid
    r = 46
    for row in range(-1, 14):
        for col in range(-1, 10):
            cx = col * r * 1.732 + (row % 2) * r * .866
            cy = row * r * 1.5
            pts = ' '.join(f'{cx + r*math.cos(math.radians(60*k+30)):.1f},{cy + r*math.sin(math.radians(60*k+30)):.1f}' for k in range(6))
            s.append(f'<polygon points="{pts}" fill="none" stroke="#fff" stroke-opacity=".05"/>')
    nodes = [(400, 470, 44, 1), (250, 330, 26, 0), (570, 300, 30, 0), (610, 560, 24, 0), (330, 640, 32, 0), (470, 790, 22, 1), (200, 520, 18, 0), (650, 420, 16, 1), (520, 160, 18, 0), (150, 720, 14, 0), (700, 700, 18, 0)]
    links = [(0,1),(0,2),(0,3),(0,4),(4,5),(1,6),(2,8),(3,7),(3,10),(4,9),(1,2),(5,10)]
    for a, b in links:
        s.append(f'<line x1="{nodes[a][0]}" y1="{nodes[a][1]}" x2="{nodes[b][0]}" y2="{nodes[b][1]}" stroke="#fff" stroke-opacity=".28" stroke-width="1.5"/>')
    for x, y, rad, g in nodes:
        s.append(f'<circle cx="{x}" cy="{y}" r="{rad+10}" fill="{GLIGHT if g else "#fff"}" opacity=".07"/>')
        s.append(f'<circle cx="{x}" cy="{y}" r="{rad}" fill="url(#{"n" if g else "nb"})"/>')
        s.append(f'<ellipse cx="{x-rad*.3:.1f}" cy="{y-rad*.38:.1f}" rx="{rad*.35:.1f}" ry="{rad*.2:.1f}" fill="#fff" opacity=".55"/>')   # specular highlight
    s.append('</svg>')
    save('sector-life.svg', '\n'.join(s))

def infra():
    W, H, WL = 800, 1000, 600
    s = [f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" role="img" aria-label="Abstract cable-stayed bridge over water">
<defs>
<linearGradient id="sky" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{NAVY}"/><stop offset="1" stop-color="#7f9bc4"/></linearGradient>
<linearGradient id="water" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#5a79a6"/><stop offset="1" stop-color="{NAVY}"/></linearGradient>
<linearGradient id="fade" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#fff" stop-opacity=".5"/><stop offset="1" stop-color="#fff" stop-opacity="0"/></linearGradient>
<mask id="rm"><rect y="{WL}" width="{W}" height="{H-WL}" fill="url(#fade)"/></mask>
</defs>
<rect width="{W}" height="{WL}" fill="url(#sky)"/>
<rect y="{WL}" width="{W}" height="{H-WL}" fill="url(#water)"/>
<circle cx="610" cy="{WL-120}" r="70" fill="#fff" opacity=".12"/><circle cx="610" cy="{WL-120}" r="34" fill="#fff" opacity=".22"/>
<g id="scene">''']
    deck_y = WL - 130
    s.append(f'<rect x="0" y="{deck_y}" width="{W}" height="12" fill="#0e1a2e"/><rect x="0" y="{deck_y}" width="{W}" height="2" fill="#fff" opacity=".4"/>')
    for px in (150, 650):
        s.append(f'<rect x="{px-6}" y="{deck_y}" width="12" height="{WL-deck_y}" fill="#0e1a2e"/>')
    tx = 400
    s.append(f'<polygon points="{tx-22},{deck_y} {tx-8},{deck_y-330} {tx+8},{deck_y-330} {tx+22},{deck_y}" fill="#0e1a2e"/>')
    s.append(f'<rect x="{tx-8}" y="{deck_y-330}" width="2" height="330" fill="#fff" opacity=".4"/>')
    for i in range(1, 11):   # stay cables fan
        ty = deck_y - 330 + i*26
        for side in (-1, 1):
            ex = tx + side * (40 + i*30)
            s.append(f'<line x1="{tx}" y1="{ty}" x2="{ex}" y2="{deck_y}" stroke="{GLIGHT if i in (3,8) else "#c9d6e8"}" stroke-width="1.3" stroke-opacity="{.85 if i in (3,8) else .55}"/>')
    s.append(f'<circle cx="{tx}" cy="{deck_y-336}" r="5" fill="{GREEN}"/>')
    s.append('</g>')
    s.append(f'<rect y="{WL}" width="{W}" height="2" fill="#fff" opacity=".3"/>')
    s.append(f'<g mask="url(#rm)" opacity=".9"><use href="#scene" transform="translate(0,{2*WL}) scale(1,-1)"/></g>')
    for i in range(10):
        s.append(f'<path d="M0,{WL+18+i*14} q 50,-4 100,0 t 100,0 t 100,0 t 100,0 t 100,0 t 100,0 t 100,0 t 100,0" fill="none" stroke="#fff" stroke-opacity="{.14-i*.012:.3f}"/>')
    s.append('</svg>')
    save('sector-infra.svg', '\n'.join(s))

hero(); fm(); subsea(); life(); infra()
print('images written to', os.path.normpath(OUT))
