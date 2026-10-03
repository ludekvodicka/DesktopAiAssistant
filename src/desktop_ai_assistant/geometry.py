import math

RING_RADII = (68, 158, 230, 298)


def point(cx, cy, r, angle):
    a = math.radians(angle)
    return cx + r * math.cos(a), cy + r * math.sin(a)


def sector(cx, cy, inner, outer, start, end):
    a, b, c, d = point(cx, cy, outer, start), point(cx, cy, outer, end), point(cx, cy, inner, end), point(cx, cy, inner, start)
    return f"M {a[0]} {a[1]} A {outer} {outer} 0 0 1 {b[0]} {b[1]} L {c[0]} {c[1]} A {inner} {inner} 0 0 0 {d[0]} {d[1]} Z"


def ring_geometry():
    inner, outer = RING_RADII[:2]
    return [{"path": sector(300, 300, inner, outer, -112.5 + i * 45, -67.5 + i * 45),
             "inner": inner, "outer": outer,
             "x": point(300, 300, 113, -90 + i * 45)[0], "y": point(300, 300, 113, -90 + i * 45)[1]} for i in range(8)]
