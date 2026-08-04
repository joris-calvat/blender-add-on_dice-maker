"""Bevel volume — banc de test (indépendant de la fabrique de dés).

Pipeline :
1. Courbe (multi-splines) → régions solid/trous → faces tessellées
2. Extrude ↑ corps
3. Extrude ↑ bande de biseau
4. Déplacer le bord selon l'angle et la hauteur de biseau
5. Résoudre les crossings (pullback) puis refermer chaque région

Paramètres : Base height (corps sans bevel, peut être 0), Angle, Bevel height, Resolution.
"""
import math

import bpy
import bmesh
from bpy.props import BoolProperty, FloatProperty, IntProperty, PointerProperty
from bpy.types import Operator, Panel, PropertyGroup
from mathutils import Vector
from mathutils.geometry import tessellate_polygon

from . import dice_maker_ui as ui

_SUFFIX_VOLUME = "-beveled-volume"
_SUFFIX_RINGS = "-bevel-rings"
_SUFFIX_CROSSINGS = "-bevel-crossings"
_TMP_SOLID = "_dm_bevel_solid_tmp"
_TMP_CUTTER = "_dm_bevel_cutter_tmp"


def bevel_output_names(src_name):
    return {
        "volume": f"{src_name}{_SUFFIX_VOLUME}",
        "rings": f"{src_name}{_SUFFIX_RINGS}",
        "crossings": f"{src_name}{_SUFFIX_CROSSINGS}",
    }


def cleanup_bevel_outputs(src_name):
    """Supprime les objets générés précédemment (noms fixes) + data orpheline."""
    removed = []
    legacy = (
        f"{src_name}-bevel-guide",
        f"{src_name}-bevel-controls",
    )
    names = list(bevel_output_names(src_name).values()) + list(legacy)
    names.extend([_TMP_SOLID, _TMP_CUTTER])
    for name in names:
        obj = bpy.data.objects.get(name)
        if obj is None:
            continue
        data = obj.data
        bpy.data.objects.remove(obj, do_unlink=True)
        removed.append(name)
        if data is not None and data.users == 0:
            if isinstance(data, bpy.types.Mesh):
                bpy.data.meshes.remove(data)
            elif isinstance(data, bpy.types.Curve):
                bpy.data.curves.remove(data)
    if removed:
        print(f"[dice_maker bevel] cleaned: {', '.join(removed)}")
    return removed


# ---------------------------------------------------------------------------
# Contour (multi-splines / trous / îlots)
# ---------------------------------------------------------------------------


def signed_area(poly):
    a = 0.0
    n = len(poly)
    for i in range(n):
        p, q = poly[i], poly[(i + 1) % n]
        a += p.x * q.y - q.x * p.y
    return 0.5 * a


def ensure_ccw(poly):
    if signed_area(poly) < 0:
        return list(reversed(poly))
    return list(poly)


def ensure_cw(poly):
    if signed_area(poly) > 0:
        return list(reversed(poly))
    return list(poly)


def point_in_poly(pt, poly):
    x, y = pt.x, pt.y
    inside = False
    n = len(poly)
    j = n - 1
    for i in range(n):
        xi, yi = poly[i].x, poly[i].y
        xj, yj = poly[j].x, poly[j].y
        if ((yi > y) != (yj > y)) and (
            x < (xj - xi) * (y - yi) / (yj - yi + 1e-30) + xi
        ):
            inside = not inside
        j = i
    return inside


def poly_perimeter(poly):
    n = len(poly)
    return sum((poly[(i + 1) % n] - poly[i]).xy.length for i in range(n))


def resample_closed(poly, count):
    """Rééchantillonne un polygone fermé en `count` points (arc-length)."""
    if len(poly) < 3:
        raise RuntimeError("loop too short")
    count = max(3, int(count))
    raw = [Vector((p.x, p.y, 0.0)) for p in poly]
    if (raw[0] - raw[-1]).length > 1e-9:
        raw.append(raw[0].copy())
    lengths = [0.0]
    for i in range(1, len(raw)):
        lengths.append(lengths[-1] + (raw[i] - raw[i - 1]).length)
    total = max(lengths[-1], 1e-9)
    out = []
    for i in range(count):
        d = total * i / count
        j = 0
        while j + 1 < len(lengths) and lengths[j + 1] < d:
            j += 1
        if j + 1 >= len(lengths):
            out.append(raw[-1].copy())
        else:
            seg = lengths[j + 1] - lengths[j]
            t = 0.0 if seg < 1e-12 else (d - lengths[j]) / seg
            out.append(raw[j].lerp(raw[j + 1], t))
    return out


def _sample_spline_raw(sp, mw, seg_n):
    raw = []
    if sp.type == "BEZIER":
        n = len(sp.bezier_points)
        if n < 2:
            return raw
        for i in range(n):
            bp0 = sp.bezier_points[i]
            bp1 = sp.bezier_points[(i + 1) % n]
            for k in range(seg_n):
                t = k / seg_n
                p0 = mw @ bp0.co
                h0 = mw @ bp0.handle_right
                h1 = mw @ bp1.handle_left
                p1 = mw @ bp1.co
                omt = 1.0 - t
                p = (
                    (omt**3) * p0
                    + 3 * (omt**2) * t * h0
                    + 3 * omt * (t**2) * h1
                    + (t**3) * p1
                )
                raw.append(Vector((p.x, p.y, 0.0)))
    else:
        pts_sp = [mw @ Vector(p.co[:3]) for p in sp.points]
        n = len(pts_sp)
        if n < 2:
            return raw
        nseg = n if sp.use_cyclic_u else max(0, n - 1)
        for i in range(nseg):
            a = pts_sp[i]
            b = pts_sp[(i + 1) % n]
            for k in range(seg_n):
                p = a.lerp(b, k / seg_n)
                p.z = 0.0
                raw.append(p)
    if len(raw) >= 2 and (raw[0] - raw[-1]).length < 1e-6:
        raw.pop()
    return raw


def curve_loops(obj, total_count):
    """Une polyline fermée par spline, budget de points réparti au périmètre."""
    mw = obj.matrix_world
    raw_loops = []
    for sp in obj.data.splines:
        n_ctrl = len(sp.bezier_points) if sp.type == "BEZIER" else len(sp.points)
        seg_n = max(16, n_ctrl * 4)
        raw = _sample_spline_raw(sp, mw, seg_n)
        if len(raw) >= 3:
            raw_loops.append(raw)
    if not raw_loops:
        raise RuntimeError("curve has no usable splines")

    perims = [max(poly_perimeter(L), 1e-9) for L in raw_loops]
    total_p = sum(perims)
    loops = []
    for L, perim in zip(raw_loops, perims):
        n = max(8, int(round(total_count * perim / total_p)))
        loops.append(resample_closed(L, n))
    return loops


def curve_points(obj, count):
    """Compat : premier loop (ou seul) rééchantillonné."""
    loops = curve_loops(obj, count)
    return loops[0]


def loop_contains(a, b, ratio=0.55):
    """True si la majorité des sommets de b est dans a."""
    if len(b) == 0:
        return False
    inside = sum(1 for p in b if point_in_poly(p, a))
    return (inside / len(b)) > ratio


def classify_solid_regions(loops):
    """Hiérarchie even-odd → régions {outer CCW, holes CCW}.

    depth pair = contour de solide, depth impair = trou.
    """
    n = len(loops)
    parent = [-1] * n
    for i in range(n):
        best = -1
        best_area = 1e18
        for j in range(n):
            if i == j:
                continue
            if loop_contains(loops[j], loops[i]):
                aj = abs(signed_area(loops[j]))
                if aj < best_area:
                    best_area = aj
                    best = j
        parent[i] = best

    def depth_of(i):
        d = 0
        cur = parent[i]
        seen = set()
        while cur != -1 and cur not in seen:
            seen.add(cur)
            d += 1
            cur = parent[cur]
        return d

    depths = [depth_of(i) for i in range(n)]
    regions = []
    for i in range(n):
        if depths[i] % 2 != 0:
            continue
        outer = ensure_ccw([Vector((p.x, p.y, 0.0)) for p in loops[i]])
        holes = []
        for j in range(n):
            if parent[j] == i and depths[j] % 2 == 1:
                holes.append(
                    ensure_ccw([Vector((p.x, p.y, 0.0)) for p in loops[j]])
                )
        regions.append({"outer": outer, "holes": holes, "index": i})
    if not regions:
        raise RuntimeError("aucune région solide détectée")
    return regions


def point_in_solid(pt, regions):
    """Test remplissage : dans un outer et hors de ses trous."""
    for reg in regions:
        if not point_in_poly(pt, reg["outer"]):
            continue
        if any(point_in_poly(pt, h) for h in reg["holes"]):
            continue
        return True
    return False


def poly_bisector_normals(poly):
    """Bissectrices 2D (une par sommet), poly CCW, orientées vers l'intérieur du poly."""
    poly = ensure_ccw(poly)
    n = len(poly)
    normals = []
    for i in range(n):
        a = poly[(i - 1) % n]
        b = poly[i]
        c = poly[(i + 1) % n]
        t1 = b - a
        t2 = c - b
        t1.z = 0.0
        t2.z = 0.0
        if t1.length < 1e-12 or t2.length < 1e-12:
            normals.append(Vector((0.0, 0.0, 0.0)))
            continue
        t1.normalize()
        t2.normalize()
        n1 = Vector((-t1.y, t1.x, 0.0))
        n2 = Vector((-t2.y, t2.x, 0.0))
        bis = n1 + n2
        if bis.length < 1e-12:
            bis = n1.copy()
        else:
            bis.normalize()
        probe = Vector((b.x, b.y, 0.0)) + bis * 1e-3
        if not point_in_poly(probe, poly):
            bis = -bis
        normals.append(bis)
    return normals


def solid_pointing_normals(poly, regions):
    """Normales pointant vers le solide (outer → in, trou → hors du trou)."""
    nrms = poly_bisector_normals(poly)
    # Vérifie sur le premier sommet non dégénéré
    for i, nrm in enumerate(nrms):
        if nrm.length < 1e-12:
            continue
        probe = Vector((poly[i].x, poly[i].y, 0.0)) + nrm * 1e-3
        if not point_in_solid(probe, regions):
            nrms = [-n for n in nrms]
        break
    return nrms


def poly_inward_normals(poly):
    """Compat : bissectrices intérieures d'un seul polygone CCW."""
    return poly_bisector_normals(poly)


def offset_poly_clamped(poly, width):
    """Offset intérieur de `width`, clampé pour rester dans le polygone (bras fins → pincement)."""
    poly = ensure_ccw([Vector((p.x, p.y, 0.0)) for p in poly])
    width = max(0.0, float(width))
    if width <= 1e-12:
        return [p.copy() for p in poly]

    normals = poly_inward_normals(poly)
    inset = []
    for i, p in enumerate(poly):
        nrm = normals[i]
        if nrm.length < 1e-12:
            inset.append(p.copy())
            continue
        lo, hi = 0.0, width
        best = 0.0
        for _ in range(20):
            mid = 0.5 * (lo + hi)
            cand = Vector((p.x + nrm.x * mid, p.y + nrm.y * mid, 0.0))
            if point_in_poly(cand, poly):
                best = mid
                lo = mid
            else:
                hi = mid
        # Légère marge pour éviter faces dégénérées au fil
        best *= 0.98
        inset.append(Vector((p.x + nrm.x * best, p.y + nrm.y * best, 0.0)))
    return inset


def smooth_poly(poly, iters=2):
    """Lissage cyclique léger (conserve le nombre de points)."""
    pts = [p.copy() for p in poly]
    n = len(pts)
    if n < 3 or iters <= 0:
        return pts
    for _ in range(iters):
        nxt = []
        for i in range(n):
            a = pts[(i - 1) % n]
            b = pts[i]
            c = pts[(i + 1) % n]
            nxt.append(b * 0.5 + a * 0.25 + c * 0.25)
        pts = nxt
    for p in pts:
        p.z = 0.0
    return pts


# ---------------------------------------------------------------------------
# Meshes + boolean
# ---------------------------------------------------------------------------


def _mesh_from_bmesh(bm, name):
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    return me


def build_solid_mesh(outer, height):
    """Prisme de la silhouette, de z=0 à z=height."""
    outer = ensure_ccw([Vector((p.x, p.y, 0.0)) for p in outer])
    height = float(height)
    bm = bmesh.new()
    bot = [bm.verts.new(p) for p in outer]
    bm.verts.ensure_lookup_table()
    try:
        bm.faces.new(bot)
    except ValueError as exc:
        bm.free()
        raise RuntimeError(f"impossible de créer la face de base: {exc}") from exc

    ret = bmesh.ops.extrude_face_region(bm, geom=list(bm.faces))
    top_verts = [e for e in ret["geom"] if isinstance(e, bmesh.types.BMVert)]
    bmesh.ops.translate(bm, verts=top_verts, vec=(0.0, 0.0, height))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    return _mesh_from_bmesh(bm, "dm-bevel-solid")


def build_wedge_cutter_mesh(outer, inset, z0, z1, eps=0.05):
    """Anneau-coin : triangle outer@z0 — outer@(z1+eps) — inset@(z1+eps)."""
    n = len(outer)
    if n != len(inset) or n < 3:
        raise RuntimeError("outer/inset size mismatch")
    z_top = float(z1) + float(eps)
    z_bot = float(z0)

    bm = bmesh.new()
    A = [bm.verts.new((outer[i].x, outer[i].y, z_bot)) for i in range(n)]
    B = [bm.verts.new((outer[i].x, outer[i].y, z_top)) for i in range(n)]
    C = [bm.verts.new((inset[i].x, inset[i].y, z_top)) for i in range(n)]
    bm.verts.ensure_lookup_table()

    for i in range(n):
        j = (i + 1) % n
        try:
            bm.faces.new((A[i], A[j], B[j], B[i]))  # paroi extérieure
            bm.faces.new((B[i], B[j], C[j], C[i]))  # dessus
            bm.faces.new((A[i], C[i], C[j], A[j]))  # pente (biseau)
        except ValueError:
            # Segment dégénéré (points coalescents) : ignorer
            pass

    # Fusion locale des sommets trop proches (bras pincés)
    bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=1e-5)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    if not bm.faces:
        bm.free()
        raise RuntimeError("cutter vide (bevel width trop grand ou contour invalide)")
    return _mesh_from_bmesh(bm, "dm-bevel-cutter")


def _unlink_tmp(name):
    obj = bpy.data.objects.get(name)
    if obj is None:
        return
    data = obj.data
    bpy.data.objects.remove(obj, do_unlink=True)
    if data is not None and data.users == 0 and isinstance(data, bpy.types.Mesh):
        bpy.data.meshes.remove(data)


def boolean_difference_meshes(solid_me, cutter_me):
    """Difference via depsgraph. Copie le résultat hors de l'évalué."""
    coll = bpy.context.collection
    view = bpy.context.view_layer
    _unlink_tmp(_TMP_SOLID)
    _unlink_tmp(_TMP_CUTTER)

    work_me = solid_me.copy()
    work_me.name = "dm-bevel-work"
    solid_obj = bpy.data.objects.new(_TMP_SOLID, work_me)
    cutter_obj = bpy.data.objects.new(_TMP_CUTTER, cutter_me)
    coll.objects.link(solid_obj)
    coll.objects.link(cutter_obj)
    cutter_obj.hide_viewport = True
    cutter_obj.hide_render = True

    mod = solid_obj.modifiers.new(name="DMBevelBool", type="BOOLEAN")
    mod.operation = "DIFFERENCE"
    mod.object = cutter_obj
    result_me = None
    for solver in ("EXACT", "FLOAT"):
        try:
            mod.solver = solver
        except (TypeError, AttributeError):
            pass
        view.update()
        try:
            deps = bpy.context.evaluated_depsgraph_get()
            eval_obj = solid_obj.evaluated_get(deps)
            tmp = bpy.data.meshes.new_from_object(eval_obj)
            # Un bon résultat doit rester dans le même ordre de grandeur
            min_ok = max(8, len(solid_me.vertices) // 4)
            if tmp is None or len(tmp.vertices) < min_ok:
                print(
                    f"[dice_maker bevel] bool {solver}: "
                    f"verts={len(tmp.vertices) if tmp else 0} < {min_ok} — reject"
                )
                if tmp is not None:
                    bpy.data.meshes.remove(tmp)
                continue
            bm = bmesh.new()
            bm.from_mesh(tmp)
            result_me = bpy.data.meshes.new("dm-bevel-result")
            bm.to_mesh(result_me)
            bm.free()
            bpy.data.meshes.remove(tmp)
            break
        except Exception as exc:
            print(f"[dice_maker bevel] boolean eval ({solver}): {exc}")
            result_me = None

    # Cleanup objets tmp SANS retoucher cutter_me/work_me déjà éventuellement
    # détachés — _unlink_tmp gère la suppression des data orphelines.
    _unlink_tmp(_TMP_SOLID)
    _unlink_tmp(_TMP_CUTTER)

    if result_me is None:
        raise RuntimeError("boolean difference a échoué")

    # Libérer l'original seulement si plus personne ne l'utilise
    try:
        if solid_me.users == 0:
            bpy.data.meshes.remove(solid_me)
    except ReferenceError:
        pass
    return result_me


def _top_faces(bm, z_eps=1e-5):
    if not bm.faces:
        return []
    zmax = max(max(v.co.z for v in f.verts) for f in bm.faces)
    return [
        f
        for f in bm.faces
        if abs(sum(v.co.z for v in f.verts) / len(f.verts) - zmax) < z_eps
    ]


def segment_triangle_intersect(p0, p1, v0, v1, v2, eps=1e-8):
    """Intersection segment↔triangle (Möller–Trumbore). Retourne (point, t) ou None."""
    direction = p1 - p0
    edge1 = v1 - v0
    edge2 = v2 - v0
    h = direction.cross(edge2)
    a = edge1.dot(h)
    if abs(a) < eps:
        return None
    f = 1.0 / a
    s = p0 - v0
    u = f * s.dot(h)
    if u < 0.0 or u > 1.0:
        return None
    q = s.cross(edge1)
    v = f * direction.dot(q)
    if v < 0.0 or u + v > 1.0:
        return None
    t = f * edge2.dot(q)
    if t <= eps or t >= 1.0 - eps:
        return None
    return p0 + direction * t, t


def find_open_mesh_crossings(bm, *, z_min=None, marker_size=0.015):
    """Détecte les arêtes (bord / flanc) qui traversent une face non adjacente.

    À appeler sur un mesh **ouvert** (plateau non refermé). Retourne une liste
    de dicts {point, z, kind, edge_verts, face_verts} et un bmesh de marqueurs.
    """
    hits = []
    seen = []

    def _near(p, tol=1e-4):
        for q in seen:
            if (p - q).length < tol:
                return True
        return False

    tris = []
    for f in bm.faces:
        vs = list(f.verts)
        if len(vs) < 3:
            continue
        fverts = {v.index for v in vs}
        for i in range(1, len(vs) - 1):
            tris.append((f, vs[0], vs[i], vs[i + 1], fverts, list(vs)))

    candidates = []
    for e in bm.edges:
        va, vb = e.verts
        za, zb = va.co.z, vb.co.z
        if z_min is not None and max(za, zb) < z_min - 1e-6:
            continue
        if e.is_boundary:
            kind = "rim" if abs(za - zb) < 1e-3 else "wall"
            candidates.append((e, kind))
        elif z_min is not None and min(za, zb) >= z_min - 1e-4:
            candidates.append((e, "flank"))

    for e, kind in candidates:
        va, vb = e.verts
        edge_verts = {va.index, vb.index}
        link_face_ids = {f.index for f in e.link_faces}
        p0, p1 = va.co.copy(), vb.co.copy()
        for face, t0, t1, t2, fverts, face_vert_list in tris:
            if face.index in link_face_ids:
                continue
            if edge_verts & fverts:
                continue
            hit = segment_triangle_intersect(p0, p1, t0.co, t1.co, t2.co)
            if hit is None:
                continue
            pt, _t = hit
            if _near(pt):
                continue
            seen.append(pt.copy())
            hits.append(
                {
                    "point": pt.copy(),
                    "z": float(pt.z),
                    "kind": kind,
                    "edge_verts": (va, vb),
                    "face_verts": tuple(face_vert_list),
                }
            )

    mk = bmesh.new()
    s = float(marker_size)
    for h in hits:
        p = h["point"]
        axes = (
            (Vector((s, 0, 0)), Vector((-s, 0, 0))),
            (Vector((0, s, 0)), Vector((0, -s, 0))),
            (Vector((0, 0, s)), Vector((0, 0, -s))),
        )
        for a, b in axes:
            mva = mk.verts.new(p + a)
            mvb = mk.verts.new(p + b)
            mk.edges.new((mva, mvb))
    return hits, mk


def _smooth_cyclic_values(values, loop_ranges, iters=2):
    """Lissage cyclique 1D par loop (ex. scales de travel)."""
    out = [float(v) for v in values]
    for _ in range(max(0, iters)):
        nxt = out[:]
        for a, b in loop_ranges:
            m = b - a
            if m < 3:
                continue
            for k in range(m):
                i = a + k
                im = a + ((k - 1) % m)
                ip = a + ((k + 1) % m)
                nxt[i] = 0.5 * out[i] + 0.25 * out[im] + 0.25 * out[ip]
        out = nxt
    return out


def despike_rim_heights(matched, loop_ranges, *, iters=4):
    """Supprime les pics Z isolés sur le rim (pointes plus hautes que les voisins).

    Utilisé quand flatten_top=False : un sommet tip peut garder un travel élevé
    alors que ses voisins sont clampés → pic. On ramène les maxima locaux à la
    moyenne des voisins, puis un léger lissage.
    """
    for _ in range(max(0, iters)):
        for a, b in loop_ranges:
            m = b - a
            if m < 3:
                continue
            zs = [matched[a + k].co.z for k in range(m)]
            new_z = zs[:]
            for k in range(m):
                zp = zs[(k - 1) % m]
                zc = zs[k]
                zn = zs[(k + 1) % m]
                neigh_max = max(zp, zn)
                neigh_avg = 0.5 * (zp + zn)
                if zc > neigh_max + 1e-7:
                    new_z[k] = neigh_avg
                else:
                    new_z[k] = 0.5 * zc + 0.25 * zp + 0.25 * zn
            for k in range(m):
                matched[a + k].co.z = new_z[k]


def resolve_crossings_by_pullback(
    bm,
    matched,
    outer,
    *,
    max_travel,
    directions,
    height,
    body_h,
    flatten_top=True,
    loop_ranges=None,
    max_iters=24,
    shrink=0.82,
    neighbor_pad=1,
):
    """Réduit localement le travel des sommets impliqués dans un croisement.

    Si `flatten_top` : Z forcé à `height`.
    Sinon : Z suit la pente (travel réel × sin angle), avec lissage anti-pics.
    """
    n = len(matched)
    scales = [1.0] * n
    vert_to_i = {v: i for i, v in enumerate(matched)}
    if not loop_ranges:
        loop_ranges = [(0, n)]

    def _expand(guilty):
        expanded = set(guilty)
        for i in guilty:
            for a, b in loop_ranges:
                if a <= i < b:
                    m = b - a
                    if m <= 0:
                        break
                    local = i - a
                    for d in range(1, neighbor_pad + 1):
                        expanded.add(a + (local - d) % m)
                        expanded.add(a + (local + d) % m)
                    break
        return expanded

    def apply():
        for i, v in enumerate(matched):
            p = outer[i]
            direction = directions[i]
            if direction.length < 1e-12 or max_travel[i] < 1e-12:
                v.co = Vector((p.x, p.y, height if flatten_top else body_h))
                continue
            start = Vector((p.x, p.y, body_h))
            final = start + direction * (max_travel[i] * scales[i])
            if flatten_top:
                v.co = Vector((final.x, final.y, height))
            else:
                v.co = final.copy()
        bm.verts.ensure_lookup_table()
        bm.edges.ensure_lookup_table()
        bm.faces.ensure_lookup_table()

    apply()
    hits = []
    hits_bm = bmesh.new()
    iters = 0
    for iters in range(1, max_iters + 1):
        hits, hits_bm = find_open_mesh_crossings(bm, z_min=body_h)
        if not hits:
            break
        if iters == 1 or iters % 3 == 0:
            ui.refresh_ui(
                f"Dice Maker : resolve crossings ({len(hits)} hits, iter {iters})…"
            )
        guilty = set()
        for h in hits:
            for v in h["edge_verts"]:
                if v in vert_to_i:
                    guilty.add(vert_to_i[v])
            for v in h["face_verts"]:
                if v in vert_to_i:
                    guilty.add(vert_to_i[v])
        if not guilty:
            for i in range(n):
                scales[i] *= shrink
        else:
            for i in _expand(guilty):
                scales[i] *= shrink
        apply()
        hits_bm.free()
    else:
        hits, hits_bm = find_open_mesh_crossings(bm, z_min=body_h)

    if not flatten_top:
        # Uniformise le travel, puis abaisse les pics (pointes) via le scale
        # pour garder XY/Z cohérents sur la pente.
        scales = _smooth_cyclic_values(scales, loop_ranges, iters=3)
        apply()
        for _ in range(5):
            spiked = False
            for a, b in loop_ranges:
                m = b - a
                if m < 3:
                    continue
                zs = [matched[a + k].co.z for k in range(m)]
                for k in range(m):
                    zp = zs[(k - 1) % m]
                    zc = zs[k]
                    zn = zs[(k + 1) % m]
                    if zc > max(zp, zn) + 1e-6:
                        scales[a + k] *= 0.82
                        spiked = True
            apply()
            if not spiked:
                break
        scales = _smooth_cyclic_values(scales, loop_ranges, iters=1)
        apply()
        despike_rim_heights(matched, loop_ranges, iters=2)
        bm.verts.ensure_lookup_table()

    return hits, hits_bm, iters, scales


def _beautify_faces(bm, faces):
    """Améliore la triangulation existante (flip d'arêtes), sans changer le domaine."""
    faces = [f for f in faces if f.is_valid]
    if not faces:
        return
    for _ in range(2):
        faces = [f for f in faces if f.is_valid]
        if not faces:
            return
        edge_set = {e for f in faces for e in f.edges}
        try:
            bmesh.ops.beautify_fill(bm, faces=faces, edges=list(edge_set))
        except Exception:
            return


def _idw_z_from_rim(x, y, rim_verts, power=2.0):
    """Z intérieur approximé par inverse-distance depuis le rim (flatten off)."""
    num = 0.0
    den = 0.0
    for v in rim_verts:
        dx = v.co.x - x
        dy = v.co.y - y
        d2 = dx * dx + dy * dy
        if d2 < 1e-16:
            return v.co.z
        w = 1.0 / (d2 ** (0.5 * power))
        num += w * v.co.z
        den += w
    return (num / den) if den > 0.0 else 0.0


def _point_in_region_xy(pt, outer_poly, hole_polys):
    if not point_in_poly(pt, outer_poly):
        return False
    for h in hole_polys:
        if point_in_poly(pt, h):
            return False
    return True


def _seed_interior_points(outer_poly, hole_polys, spacing):
    """Points intérieurs pour casser les longues diagonales (CDT)."""
    if spacing <= 1e-8:
        return []
    xs = [p.x for p in outer_poly]
    ys = [p.y for p in outer_poly]
    seeds = []
    x = min(xs) + 0.5 * spacing
    while x <= max(xs):
        y = min(ys) + 0.5 * spacing
        while y <= max(ys):
            pt = Vector((x, y, 0.0))
            if _point_in_region_xy(pt, outer_poly, hole_polys):
                seeds.append(pt)
            y += spacing
        x += spacing
    return seeds


def _boundary_edge_spacing(loops):
    """Espacement cible ≈ médiane des arêtes du contour."""
    lengths = []
    for loop in loops:
        n = len(loop)
        for i in range(n):
            a = loop[i].co
            b = loop[(i + 1) % n].co
            lengths.append((a.xy - b.xy).length)
    if not lengths:
        return 0.15
    lengths.sort()
    med = lengths[len(lengths) // 2]
    # Un peu plus large que le rim pour ne pas exploser le nombre de faces
    return max(med * 1.6, 0.05)


def _tessellate_via_cdt(bm, outer_verts, holes, seed_interior=True):
    """Constrained Delaunay (+ graines intérieures optionnelles)."""
    try:
        from mathutils.geometry import delaunay_2d_cdt
    except ImportError:
        return []

    # Outer CCW, holes CW (convention CDT / winding)
    def _order_bm(loop, want_ccw):
        area = signed_area([Vector((v.co.x, v.co.y, 0.0)) for v in loop])
        if want_ccw:
            return list(loop) if area >= 0 else list(reversed(loop))
        return list(loop) if area <= 0 else list(reversed(loop))

    outer_ordered = _order_bm(outer_verts, want_ccw=True)
    outer_poly = [Vector((v.co.x, v.co.y, 0.0)) for v in outer_ordered]
    hole_polys = []
    hole_loops = []
    for hole in holes:
        ordered = _order_bm(hole, want_ccw=False)
        hole_loops.append(ordered)
        hole_polys.append([Vector((v.co.x, v.co.y, 0.0)) for v in ordered])

    loops = [outer_ordered] + hole_loops
    verts_2d = []
    bm_map = []  # BMVert ou None (graine)
    edges = []
    for loop in loops:
        start = len(verts_2d)
        for v in loop:
            verts_2d.append(Vector((v.co.x, v.co.y)))
            bm_map.append(v)
        n = len(loop)
        for i in range(n):
            edges.append((start + i, start + ((i + 1) % n)))

    outer_face = list(range(len(outer_ordered)))

    seeds = []
    spacing = 0.0
    if seed_interior:
        spacing = _boundary_edge_spacing(loops)
        seeds = _seed_interior_points(outer_poly, hole_polys, spacing)
        if len(seeds) > 800:
            spacing *= (len(seeds) / 800.0) ** 0.5
            seeds = _seed_interior_points(outer_poly, hole_polys, spacing)
        for s in seeds:
            verts_2d.append(Vector((s.x, s.y)))
            bm_map.append(None)

    if len(verts_2d) < 3:
        return []

    rim_all = [v for v in bm_map if v is not None]
    # output_type 3 : contraintes + détection de trous
    try:
        coords, _oe, faces_out, orig_verts, _oedges, _ofaces = delaunay_2d_cdt(
            verts_2d, edges, [outer_face], 3, 1e-6, True
        )
    except Exception as exc:
        print(f"[dice_maker bevel] CDT failed: {exc}")
        return []

    print(
        f"[dice_maker bevel] CDT seeds={len(seeds)} spacing={spacing:.4f} "
        f"out_faces={len(faces_out)}"
    )

    steiner_cache = {}
    created = []
    snap_eps2 = (1e-4) ** 2

    def map_vert(idx):
        if idx in steiner_cache:
            return steiner_cache[idx]
        ov = orig_verts[idx] if idx < len(orig_verts) else []
        if not isinstance(ov, (list, tuple)):
            ov = [ov] if ov is not None else []
        for src in ov:
            if src is None:
                continue
            if 0 <= src < len(bm_map) and bm_map[src] is not None:
                steiner_cache[idx] = bm_map[src]
                return bm_map[src]
        c = coords[idx]
        # Snap sur un sommet rim existant (évite doublons → non-manifold après merge)
        best = None
        best_d = snap_eps2
        for v in rim_all:
            d = (v.co.x - c.x) ** 2 + (v.co.y - c.y) ** 2
            if d < best_d:
                best_d = d
                best = v
        if best is not None:
            steiner_cache[idx] = best
            return best
        z = _idw_z_from_rim(c.x, c.y, rim_all)
        nv = bm.verts.new((c.x, c.y, z))
        steiner_cache[idx] = nv
        return nv

    def edge_saturated(a, b):
        for e in a.link_edges:
            if e.other_vert(a) is b and len(e.link_faces) >= 2:
                return True
        return False

    for face in faces_out:
        if len(face) < 3:
            continue
        try:
            tri = [map_vert(face[0]), map_vert(face[1]), map_vert(face[2])]
        except (IndexError, ReferenceError, ValueError):
            continue
        if tri[0] is tri[1] or tri[1] is tri[2] or tri[0] is tri[2]:
            continue
        cx = (tri[0].co.x + tri[1].co.x + tri[2].co.x) / 3.0
        cy = (tri[0].co.y + tri[1].co.y + tri[2].co.y) / 3.0
        if not _point_in_region_xy(Vector((cx, cy, 0.0)), outer_poly, hole_polys):
            continue
        # Ne pas empiler une 3e face sur une arête déjà pleine
        if (
            edge_saturated(tri[0], tri[1])
            or edge_saturated(tri[1], tri[2])
            or edge_saturated(tri[2], tri[0])
        ):
            continue
        try:
            f = bm.faces.new(tri)
            created.append(f)
        except ValueError:
            continue

    if steiner_cache:
        bm.verts.ensure_lookup_table()
    return created


def _tessellate_region_faces(bm, outer_verts, hole_vert_lists, seed_interior=True):
    """Remplit une région (outer + trous) sans longues traverses.

    1) Constrained Delaunay (+ graines si seed_interior)
    2) Fallback tessellate_polygon + beautify
    """
    if len(outer_verts) < 3:
        return 0

    holes = [h for h in hole_vert_lists if len(h) >= 3]
    created = _tessellate_via_cdt(
        bm, outer_verts, holes, seed_interior=seed_interior
    )
    used_cdt = bool(created)

    if not created:
        flat_verts = list(outer_verts)
        polys = [[Vector((v.co.x, v.co.y)) for v in outer_verts]]
        for hole in holes:
            area = signed_area([Vector((v.co.x, v.co.y, 0.0)) for v in hole])
            ordered = list(reversed(hole)) if area > 0 else list(hole)
            flat_verts.extend(ordered)
            polys.append([Vector((v.co.x, v.co.y)) for v in ordered])
        try:
            tris = tessellate_polygon(polys)
        except Exception as exc:
            print(f"[dice_maker bevel] tessellate failed: {exc}")
            return 0
        for t in tris:
            try:
                f = bm.faces.new(
                    (flat_verts[t[0]], flat_verts[t[1]], flat_verts[t[2]])
                )
                created.append(f)
            except ValueError:
                continue

    # beautify sur CDT+graines crée souvent du non-manifold avec les murs
    if created and not used_cdt:
        _beautify_faces(bm, created)
    return len([f for f in created if f.is_valid])


def close_regions_top(bm, region_rims, merge_dist=1e-4):
    """Referme chaque région séparément (sommets au Z courant, plat ou non)."""
    total = 0
    rim_verts = []
    for rim in region_rims:
        total += _tessellate_region_faces(
            bm, rim["outer"], rim["holes"], seed_interior=True
        )
        rim_verts.extend(rim["outer"])
        for h in rim["holes"]:
            rim_verts.extend(h)
    if rim_verts and merge_dist > 0:
        # Un seul merge : après ça, les refs rim sont invalidées
        unique = []
        seen = set()
        for v in rim_verts:
            if id(v) in seen:
                continue
            seen.add(id(v))
            try:
                if v.is_valid:
                    unique.append(v)
            except ReferenceError:
                continue
        if unique:
            bmesh.ops.remove_doubles(bm, verts=unique, dist=merge_dist)
    bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
    return total


def write_crossings_object(hits_bm, name):
    """Écrit (ou remplace) l'objet debug des croisements."""
    me = bpy.data.meshes.new(name + "_mesh")
    hits_bm.to_mesh(me)
    hits_bm.free()
    obj = bpy.data.objects.get(name)
    if obj is None:
        obj = bpy.data.objects.new(name, me)
        bpy.context.collection.objects.link(obj)
    else:
        old = obj.data
        obj.data = me
        if old and old.users == 0:
            bpy.data.meshes.remove(old)
    mat = bpy.data.materials.get("BevelCrossings") or bpy.data.materials.new(
        "BevelCrossings"
    )
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        bsdf.inputs["Base Color"].default_value = (0.95, 0.15, 0.1, 1.0)
        bsdf.inputs["Emission Color"].default_value = (0.95, 0.2, 0.1, 1.0)
        try:
            bsdf.inputs["Emission Strength"].default_value = 2.0
        except KeyError:
            pass
    if obj.data.materials:
        obj.data.materials[0] = mat
    else:
        obj.data.materials.append(mat)
    obj.location = (0, 0, 0)
    obj.hide_set(False)
    obj.show_in_front = True
    return obj


def build_extrude_move_cut_mesh(
    regions,
    *,
    base_height=0.8,
    angle=45.0,
    bevel_height=0.2,
    flatten_top=True,
):
    """Régions → extrude base → extrude biseau → move → resolve → close.

    `flatten_top` : si True, le plateau est forcé à base+bevel même quand le
    travel est réduit ; si False, le Z suit la pente (points « coupés » plus bas).
    """
    if not regions:
        raise RuntimeError("aucune région")

    body_h = max(0.0, float(base_height))
    bh = max(0.0, float(bevel_height))
    if body_h < 1e-12 and bh < 1e-12:
        raise RuntimeError("Base height ou Bevel height doit être > 0")

    ang_deg = max(1.0, min(89.0, float(angle)))
    ang = math.radians(ang_deg)
    cos_a = math.cos(ang)
    sin_a = math.sin(ang)
    # Longueur le long de la pente pour monter exactement bevel_height
    dist = (bh / sin_a) if bh > 1e-12 else 0.0
    height = body_h + bh
    flatten_top = bool(flatten_top)

    bm = bmesh.new()
    rim_loops = []
    for reg in regions:
        outer = reg["outer"]
        holes = reg["holes"]
        o_verts = [bm.verts.new(p) for p in outer]
        h_vert_lists = [[bm.verts.new(p) for p in h] for h in holes]
        bm.verts.ensure_lookup_table()
        # Fond : pas de graines (évite un plateau intérieur qui survivrait à l'extrude)
        nfaces = _tessellate_region_faces(
            bm, o_verts, h_vert_lists, seed_interior=False
        )
        if nfaces == 0:
            bm.free()
            raise RuntimeError("impossible de tesseller une région")
        rim_loops.append(
            {
                "pts": outer,
                "normals": solid_pointing_normals(outer, regions),
                "bot": o_verts,
                "is_hole": False,
            }
        )
        for h, hv in zip(holes, h_vert_lists):
            rim_loops.append(
                {
                    "pts": h,
                    "normals": solid_pointing_normals(h, regions),
                    "bot": hv,
                    "is_hole": True,
                }
            )

    print(
        f"[dice_maker bevel] regions={len(regions)} rim_loops={len(rim_loops)} "
        f"base_faces={len(bm.faces)} base_h={body_h:.4f} bevel_h={bh:.4f} "
        f"angle={ang_deg:.1f}°"
    )

    def extrude_up(dz, remove_old_cap):
        faces = _top_faces(bm)
        if not faces:
            return []
        old_faces = list(faces)
        ret = bmesh.ops.extrude_face_region(bm, geom=old_faces)
        if remove_old_cap:
            bmesh.ops.delete(bm, geom=old_faces, context="FACES")
        new_verts = [e for e in ret["geom"] if isinstance(e, bmesh.types.BMVert)]
        if dz and new_verts:
            bmesh.ops.translate(bm, verts=new_verts, vec=(0.0, 0.0, dz))
        return new_verts

    # Corps sans bevel (peut être 0 → on ne monte que le biseau)
    if body_h > 1e-8:
        extrude_up(body_h, remove_old_cap=False)
    if bh > 1e-8:
        # Si pas de corps, première extrude : garder le fond
        extrude_up(bh, remove_old_cap=(body_h > 1e-8))
    elif body_h > 1e-8:
        # Pas de biseau : prisme simple, déjà fermé
        solid_me = bpy.data.meshes.new("dm-bevel-solid")
        bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
        bm.to_mesh(solid_me)
        nverts_bm = len(bm.verts)
        bm.free()
        bm2 = bmesh.new()
        bm2.from_mesh(solid_me)
        boundary = sum(1 for e in bm2.edges if e.is_boundary)
        nonman = sum(1 for e in bm2.edges if not e.is_manifold)
        nverts = len(bm2.verts)
        bm2.free()
        empty_hits = bmesh.new()
        info = {
            "mode": "base_only",
            "base_height": body_h,
            "bevel_height": 0.0,
            "angle": ang_deg,
            "vert_drop": 0.0,
            "body_h": body_h,
            "boundary": boundary,
            "nonmanifold": nonman,
            "nverts": nverts,
            "inset_travel_avg": 0.0,
            "crossings": 0,
            "crossings_before": 0,
            "resolve_iters": 0,
            "crossing_z_min": None,
            "crossing_z_max": None,
            "regions": len(regions),
            "top_faces": 0,
            "hits_bm": empty_hits,
            "hits": [],
        }
        print(f"[dice_maker bevel] base_only verts={nverts_bm}")
        return solid_me, info

    # Associer chaque point de rim → sommet du plateau
    top_fs = _top_faces(bm)
    top_verts = []
    seen = set()
    for f in top_fs:
        for v in f.verts:
            if v.index not in seen:
                seen.add(v.index)
                top_verts.append(v)

    matched = []
    outer_pts = []
    normals = []
    loop_ranges = []
    used = set()
    for loop in rim_loops:
        start = len(matched)
        for p in loop["pts"]:
            best = None
            best_d = 1e18
            for v in top_verts:
                if v.index in used:
                    continue
                d = (v.co.x - p.x) ** 2 + (v.co.y - p.y) ** 2
                if d < best_d:
                    best_d = d
                    best = v
            if best is None:
                raise RuntimeError("matching plateau incomplet")
            used.add(best.index)
            matched.append(best)
            outer_pts.append(Vector((p.x, p.y, 0.0)))
        normals.extend(loop["normals"])
        loop_ranges.append((start, len(matched)))

    n = len(matched)
    max_travel = []
    directions = []
    for i in range(n):
        p = outer_pts[i]
        nrm = normals[i]
        direction = Vector((nrm.x * cos_a, nrm.y * cos_a, sin_a))
        if direction.length < 1e-12:
            directions.append(Vector((0, 0, 0)))
            max_travel.append(0.0)
            continue
        direction.normalize()
        directions.append(direction)
        start = Vector((p.x, p.y, body_h))
        lo, hi = 0.0, dist
        best = 0.0
        for _ in range(22):
            mid = 0.5 * (lo + hi)
            cand = start + direction * mid
            if point_in_solid(Vector((cand.x, cand.y, 0.0)), regions):
                best = mid
                lo = mid
            else:
                hi = mid
        max_travel.append(best * 0.98)

    # Appliquer + lissage par loop
    def _set_rim(i, xy, travel_or_none=None):
        p = outer_pts[i]
        d = directions[i]
        if d.length < 1e-12 or max_travel[i] < 1e-12:
            matched[i].co = Vector((p.x, p.y, height if flatten_top else body_h))
            return
        start = Vector((p.x, p.y, body_h))
        if travel_or_none is None:
            travel = max_travel[i]
        else:
            travel = travel_or_none
        final = start + d * travel
        if flatten_top:
            matched[i].co = Vector((xy.x, xy.y, height))
        else:
            # Conserve le Z de pente correspondant au travel XY projeté
            matched[i].co = Vector((xy.x, xy.y, final.z))

    for a, b in loop_ranges:
        dests = []
        for i in range(a, b):
            p = outer_pts[i]
            d = directions[i]
            if d.length < 1e-12 or max_travel[i] < 1e-12:
                dests.append(Vector((p.x, p.y, 0.0)))
                _set_rim(i, p)
                continue
            start = Vector((p.x, p.y, body_h))
            final = start + d * max_travel[i]
            dests.append(Vector((final.x, final.y, 0.0)))
            _set_rim(i, final, max_travel[i])
        dests = smooth_poly(dests, iters=1)
        for k, i in enumerate(range(a, b)):
            d = directions[i]
            if d.length < 1e-12:
                continue
            p = outer_pts[i]
            start = Vector((p.x, p.y, body_h))
            target = Vector((dests[k].x, dests[k].y, height))
            proj = max(0.0, (target - start).dot(d))
            max_travel[i] = min(max_travel[i], proj)
            _set_rim(i, dests[k], max_travel[i])

    if not flatten_top:
        # Lisse le travel avant crossings, casse les pics Z aux pointes
        max_travel[:] = _smooth_cyclic_values(max_travel, loop_ranges, iters=2)
        for i, v in enumerate(matched):
            p = outer_pts[i]
            d = directions[i]
            if d.length < 1e-12 or max_travel[i] < 1e-12:
                v.co = Vector((p.x, p.y, body_h))
                continue
            start = Vector((p.x, p.y, body_h))
            v.co = (start + d * max_travel[i]).copy()
        despike_rim_heights(matched, loop_ranges, iters=3)

    # Ouvrir le haut (faces du plateau) avant resolve/close
    matched_set = set(matched)
    top_cap = [f for f in bm.faces if all(v in matched_set for v in f.verts)]
    if not top_cap:
        # Filet de sécurité si des sommets intérieurs existent encore
        top_cap = _top_faces(bm, z_eps=1e-4)
    if top_cap:
        top_verts = {v for f in top_cap for v in f.verts}
        bmesh.ops.delete(bm, geom=list(top_cap), context="FACES")
        orphans = [
            v
            for v in top_verts
            if v.is_valid and v not in matched_set and not v.link_faces
        ]
        if orphans:
            bmesh.ops.delete(bm, geom=orphans, context="VERTS")
    bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))

    hits_before, _tmp = find_open_mesh_crossings(bm, z_min=body_h)
    _tmp.free()
    n_before = len(hits_before)

    hits, hits_bm, n_iters, scales = resolve_crossings_by_pullback(
        bm,
        matched,
        outer_pts,
        max_travel=max_travel,
        directions=directions,
        height=height,
        body_h=body_h,
        flatten_top=flatten_top,
        loop_ranges=loop_ranges,
    )
    z_hits = [h["z"] for h in hits]
    print(
        f"[dice_maker bevel] crossings {n_before} → {len(hits)} "
        f"(iters={n_iters}, scale_min={min(scales) if scales else 1:.3f})"
        + (
            f" residual_z=[{min(z_hits):.4f}, {max(z_hits):.4f}]"
            if z_hits
            else ""
        )
    )

    # Refermer chaque région (outer + ses trous), sans fusionner les zones
    region_rims = []
    # rim_loops order: for each region, outer then its holes
    idx = 0
    for reg in regions:
        a, b = loop_ranges[idx]
        outer_v = matched[a:b]
        idx += 1
        hole_vs = []
        for _ in reg["holes"]:
            a, b = loop_ranges[idx]
            hole_vs.append(matched[a:b])
            idx += 1
        region_rims.append({"outer": outer_v, "holes": hole_vs})

    n_top = close_regions_top(bm, region_rims, merge_dist=5e-4)
    # Ne plus toucher aux refs `matched` / `region_rims` : remove_doubles les invalide.
    bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
    print(f"[dice_maker bevel] top faces created≈{n_top} flatten_top={flatten_top}")

    solid_me = bpy.data.meshes.new("dm-bevel-solid")
    bm.to_mesh(solid_me)
    nverts_bm = len(bm.verts)
    bm.free()
    print(f"[dice_maker bevel] after resolve+close verts={nverts_bm}")

    travels = [max_travel[i] * scales[i] * cos_a for i in range(n)]
    travel_avg = sum(travels) / max(n, 1)
    mode = "extrude_move_resolved" if not hits else "extrude_move_resolved_residual"
    result_me = solid_me

    bm2 = bmesh.new()
    bm2.from_mesh(result_me)
    bmesh.ops.remove_doubles(bm2, verts=list(bm2.verts), dist=1e-5)
    bmesh.ops.recalc_face_normals(bm2, faces=list(bm2.faces))
    boundary = sum(1 for e in bm2.edges if e.is_boundary)
    nonman = sum(1 for e in bm2.edges if not e.is_manifold)
    nverts = len(bm2.verts)
    # Compter les composants / faces top
    zmax = max((v.co.z for v in bm2.verts), default=0.0)
    top_faces = [
        f
        for f in bm2.faces
        if abs(sum(v.co.z for v in f.verts) / len(f.verts) - zmax) < 1e-3
    ]
    bm2.to_mesh(result_me)
    bm2.free()

    info = {
        "mode": mode,
        "base_height": body_h,
        "bevel_height": bh,
        "angle": ang_deg,
        "flatten_top": flatten_top,
        "vert_drop": bh,
        "body_h": body_h,
        "boundary": boundary,
        "nonmanifold": nonman,
        "nverts": nverts,
        "inset_travel_avg": travel_avg,
        "crossings": len(hits),
        "crossings_before": n_before,
        "resolve_iters": n_iters,
        "crossing_z_min": min(z_hits) if z_hits else None,
        "crossing_z_max": max(z_hits) if z_hits else None,
        "regions": len(regions),
        "top_faces": len(top_faces),
        "hits_bm": hits_bm,
        "hits": hits,
    }
    return result_me, info


def write_volume_object(me, name):
    obj = bpy.data.objects.get(name)
    if obj is None:
        obj = bpy.data.objects.new(name, me)
        bpy.context.collection.objects.link(obj)
    else:
        old = obj.data
        obj.data = me
        if old and old.users == 0:
            bpy.data.meshes.remove(old)

    mat = bpy.data.materials.get("BeveledVolume") or bpy.data.materials.new(
        "BeveledVolume"
    )
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        bsdf.inputs["Base Color"].default_value = (0.75, 0.55, 0.35, 1.0)
        bsdf.inputs["Roughness"].default_value = 0.45
    if obj.data.materials:
        obj.data.materials[0] = mat
    else:
        obj.data.materials.append(mat)
    obj.location = (0, 0, 0)
    obj.hide_set(False)
    return obj


def build_beveled_volume(
    src,
    *,
    base_height=0.8,
    angle=45.0,
    bevel_height=0.2,
    resolution=256,
    flatten_top=True,
):
    """Construit le volume bevel. Retourne (volume_obj, info)."""
    if src is None or src.type != "CURVE":
        raise TypeError("La source doit être un objet CURVE")

    names = bevel_output_names(src.name)
    cleanup_bevel_outputs(src.name)

    muted = []
    for m in src.modifiers:
        muted.append((m, m.show_viewport, m.show_render))
        m.show_viewport = False
        m.show_render = False

    try:
        if hasattr(src.data, "bevel_depth"):
            src.data.bevel_depth = 0.0
        src.hide_set(False)
        src.hide_viewport = False

        res = max(32, int(resolution))
        loops = curve_loops(src, res)
        regions = classify_solid_regions(loops)
        print(
            f"[dice_maker bevel] src={src.name} loops={len(loops)} "
            f"regions={len(regions)} "
            + ", ".join(
                f"R{i}(outer={len(r['outer'])},holes={len(r['holes'])})"
                for i, r in enumerate(regions)
            )
        )
        me, info = build_extrude_move_cut_mesh(
            regions,
            base_height=base_height,
            angle=angle,
            bevel_height=bevel_height,
            flatten_top=flatten_top,
        )
        volume = write_volume_object(me, names["volume"])
        hits_bm = info.pop("hits_bm", None)
        hits = info.pop("hits", None) or []
        if hits_bm is not None:
            if hits:
                write_crossings_object(hits_bm, names["crossings"])
            else:
                hits_bm.free()
                old = bpy.data.objects.get(names["crossings"])
                if old is not None:
                    data = old.data
                    bpy.data.objects.remove(old, do_unlink=True)
                    if data and data.users == 0:
                        bpy.data.meshes.remove(data)

        print(
            f"[dice_maker bevel] src={src.name} vol={volume.name} "
            f"mode={info['mode']} regions={info.get('regions', 1)} "
            f"base_h={info['base_height']:.4f} bevel_h={info['bevel_height']:.4f} "
            f"angle={info['angle']:.1f}° travel_avg={info['inset_travel_avg']:.4f} "
            f"boundary={info['boundary']} nonmanifold={info['nonmanifold']} "
            f"verts={info['nverts']} top_faces={info.get('top_faces', '?')} "
            f"crossings={info.get('crossings_before', '?')}→{info.get('crossings', 0)} "
            f"iters={info.get('resolve_iters', 0)}"
        )
        if info.get("crossing_z_min") is not None:
            print(
                f"[dice_maker bevel] residual crossing Z "
                f"[{info['crossing_z_min']:.4f}, {info['crossing_z_max']:.4f}]"
            )
        if info["boundary"] or info["nonmanifold"]:
            print(
                f"[dice_maker bevel] ATTENTION mesh non idéal "
                f"(boundary={info['boundary']}, nonmanifold={info['nonmanifold']})"
            )
        return volume, info
    finally:
        for m, vp, rp in muted:
            m.show_viewport = vp
            m.show_render = rp
        src.hide_set(False)


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------


class DiceMakerBevelProperties(PropertyGroup):
    """Paramètres du volume bevel."""

    base_height: FloatProperty(
        name="Base Height",
        description="Hauteur du corps sans bevel (0 = biseau dès le bas)",
        default=0.8,
        min=0.0,
        max=100.0,
        subtype="DISTANCE",
    )
    angle: FloatProperty(
        name="Angle",
        description="Angle du bevel depuis l'horizontale (1°≈plat, 45°=chanfrein, 89°≈vertical)",
        default=45.0,
        min=1.0,
        max=89.0,
    )
    bevel_height: FloatProperty(
        name="Bevel Height",
        description="Hauteur verticale du biseau (0 = prisme sans bevel)",
        default=0.2,
        min=0.0,
        max=100.0,
        subtype="DISTANCE",
    )
    resolution: IntProperty(
        name="Resolution",
        description="Nombre de points sur le contour source",
        default=256,
        min=32,
        max=1024,
    )
    flatten_top: BoolProperty(
        name="Flatten Top",
        description=(
            "Si activé : plateau forcé à Base+Bevel height même si le travel "
            "est réduit (pinch/crossings). "
            "Si désactivé : le Z suit la pente — les points limités restent plus bas."
        ),
        default=True,
    )


class DICE_MAKER_OT_test_bevel_volume(Operator):
    """Tester le volume bevel sur la courbe active"""

    bl_idname = "dice_maker.test_bevel_volume"
    bl_label = "Build Bevel Volume"
    bl_description = (
        "Base height + angle + bevel height. "
        "Banc de test — non branché sur Create Dice."
    )
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        src = context.active_object
        if src is None or src.type != "CURVE":
            self.report(
                {"ERROR"},
                "Sélectionne une courbe (objet actif de type Curve)",
            )
            return {"CANCELLED"}

        if context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")

        props = context.scene.dice_maker_bevel_props
        src_name = src.name
        try:
            volume, info = build_beveled_volume(
                src,
                base_height=props.base_height,
                angle=float(props.angle),
                bevel_height=props.bevel_height,
                resolution=props.resolution,
                flatten_top=props.flatten_top,
            )
        except Exception as exc:
            import traceback

            traceback.print_exc()
            self.report({"ERROR"}, str(exc))
            src = bpy.data.objects.get(src_name)
            if src is not None:
                bpy.ops.object.select_all(action="DESELECT")
                src.select_set(True)
                context.view_layer.objects.active = src
            return {"CANCELLED"}

        src = bpy.data.objects.get(src_name) or src
        src.hide_set(False)
        bpy.ops.object.select_all(action="DESELECT")
        src.select_set(True)
        context.view_layer.objects.active = src

        self.report(
            {"INFO"},
            f"Volume: {volume.name} ({info['mode']}, "
            f"{info.get('crossings_before', 0)}→{info.get('crossings', 0)} cross, "
            f"{info['nverts']} verts)",
        )
        return {"FINISHED"}


class DICE_MAKER_PT_bevel_test(Panel):
    """Section séparée — banc de test bevel."""

    bl_label = "Bevel Volume (test)"
    bl_idname = "DICE_MAKER_PT_bevel_test"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Dice Maker"
    bl_options = {"DEFAULT_CLOSED"}

    def draw_header(self, context):
        self.layout.label(text="", icon="MOD_BEVEL")

    def draw(self, context):
        layout = self.layout
        props = getattr(context.scene, "dice_maker_bevel_props", None)
        if props is None:
            layout.label(text="Recharge l'addon (Reload Scripts)", icon="ERROR")
            return

        col = layout.column(align=True)
        col.label(text="base → bevel (angle + hauteur)")
        col.label(text="Sortie: *-beveled-volume")
        layout.separator()

        src = context.active_object
        if src is None or src.type != "CURVE":
            box = layout.box()
            box.label(text="Sélectionne une Curve", icon="ERROR")
        else:
            layout.label(text=f"Source: {src.name}", icon="CURVE_DATA")

        layout.prop(props, "base_height")
        layout.prop(props, "angle")
        layout.prop(props, "bevel_height")
        layout.prop(props, "resolution")
        layout.prop(props, "flatten_top")
        layout.separator()
        layout.operator(
            "dice_maker.test_bevel_volume",
            text="Build Bevel Volume",
            icon="MESH_CUBE",
        )


classes = (
    DiceMakerBevelProperties,
    DICE_MAKER_OT_test_bevel_volume,
    DICE_MAKER_PT_bevel_test,
)


def register():
    for cls in classes:
        try:
            bpy.utils.register_class(cls)
        except ValueError:
            bpy.utils.unregister_class(cls)
            bpy.utils.register_class(cls)
    bpy.types.Scene.dice_maker_bevel_props = PointerProperty(
        type=DiceMakerBevelProperties
    )


def unregister():
    if hasattr(bpy.types.Scene, "dice_maker_bevel_props"):
        del bpy.types.Scene.dice_maker_bevel_props
    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass
