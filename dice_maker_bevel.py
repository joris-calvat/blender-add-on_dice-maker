"""Bevel volume — banc de test (indépendant de la fabrique de dés).

Pipeline :
1. Courbe → maillage (face)
2. Extrude ↑ corps
3. Extrude ↑ bande de biseau
4. Déplacer les points du haut : normale intérieure + angle (vers le haut) × distance
5. Coupe booléenne avec un cutter au-dessus (anneau en coin)
"""
import math

import bpy
import bmesh
from bpy.props import FloatProperty, IntProperty, PointerProperty
from bpy.types import Operator, Panel, PropertyGroup
from mathutils import Vector

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
# Contour
# ---------------------------------------------------------------------------


def curve_points(obj, count):
    """Échantillonne la silhouette en `count` points (arc-length)."""
    mw = obj.matrix_world
    raw = []
    for sp in obj.data.splines:
        if sp.type == "BEZIER":
            n = len(sp.bezier_points)
            seg_n = max(24, (count * 4 + n - 1) // max(n, 1))
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
            seg_n = max(8, (count * 2 + n - 1) // max(n, 1))
            for i in range(n if sp.use_cyclic_u else max(0, n - 1)):
                a = pts_sp[i]
                b = pts_sp[(i + 1) % n]
                for k in range(seg_n):
                    p = a.lerp(b, k / seg_n)
                    p.z = 0.0
                    raw.append(p)
    if len(raw) < 3:
        raise RuntimeError("curve has too few points")
    if (raw[0] - raw[-1]).length > 1e-6:
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


def poly_inward_normals(poly):
    """Bissectrices 2D intérieures (une par sommet), poly CCW."""
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


def resolve_crossings_by_pullback(
    bm,
    matched,
    outer,
    normals,
    *,
    max_travel,
    directions,
    height,
    body_h,
    max_iters=24,
    shrink=0.82,
    neighbor_pad=1,
):
    """Réduit localement le travel des sommets impliqués dans un croisement.

    Retourne (hits_restants, hits_bm, n_iters, scales).
    """
    n = len(matched)
    scales = [1.0] * n
    vert_to_i = {v: i for i, v in enumerate(matched)}

    def apply():
        for i, v in enumerate(matched):
            p = outer[i]
            direction = directions[i]
            if direction.length < 1e-12 or max_travel[i] < 1e-12:
                v.co = Vector((p.x, p.y, height))
                continue
            start = Vector((p.x, p.y, body_h))
            final = start + direction * (max_travel[i] * scales[i])
            v.co = Vector((final.x, final.y, height))
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
        guilty = set()
        for h in hits:
            for v in h["edge_verts"]:
                if v in vert_to_i:
                    guilty.add(vert_to_i[v])
            for v in h["face_verts"]:
                if v in vert_to_i:
                    guilty.add(vert_to_i[v])
        if not guilty:
            # Fallback : shrink global léger si on n'a pas pu mapper
            for i in range(n):
                scales[i] *= shrink
        else:
            expanded = set(guilty)
            for i in guilty:
                for d in range(1, neighbor_pad + 1):
                    expanded.add((i - d) % n)
                    expanded.add((i + d) % n)
            for i in expanded:
                scales[i] *= shrink
        apply()
        hits_bm.free()
    else:
        hits, hits_bm = find_open_mesh_crossings(bm, z_min=body_h)

    return hits, hits_bm, iters, scales


def close_open_top(bm, height, merge_dist=1e-4):
    """Referme le plateau (boucle boundary haute) et nettoie."""
    # Remplir les trous (plateau ouvert)
    boundary = [e for e in bm.edges if e.is_boundary]
    if boundary:
        try:
            bmesh.ops.holes_fill(bm, edges=boundary, sides=0)
        except Exception:
            # Fallback : une face si une seule boucle de verts au sommet
            rim = [
                v
                for v in bm.verts
                if abs(v.co.z - height) < 1e-3 and any(e.is_boundary for e in v.link_edges)
            ]
            if len(rim) >= 3:
                # Ordonner approximativement via angle autour du centroïde
                c = Vector((0, 0, 0))
                for v in rim:
                    c += v.co
                c /= len(rim)
                rim.sort(
                    key=lambda v: math.atan2(v.co.y - c.y, v.co.x - c.x)
                )
                try:
                    bm.faces.new(rim)
                except ValueError:
                    pass

    top = [v for v in bm.verts if abs(v.co.z - height) < 1e-3]
    if top and merge_dist > 0:
        bmesh.ops.remove_doubles(bm, verts=top, dist=merge_dist)
    bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))


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
    outer,
    *,
    height=1.0,
    angle=45.0,
    distance=0.25,
):
    """1 face → extrude → move → resolve crossings → close top."""
    outer = ensure_ccw([Vector((p.x, p.y, 0.0)) for p in outer])
    if len(outer) < 3:
        raise RuntimeError("contour trop court")

    height = max(1e-4, float(height))
    ang = math.radians(max(0.0, min(89.0, float(angle))))
    dist = max(0.0, float(distance))
    cos_a = math.cos(ang)
    sin_a = math.sin(ang)
    vert = min(dist * sin_a, height * 0.95)
    body_h = max(0.0, height - vert)
    bh = height - body_h
    normals = poly_inward_normals(outer)
    n = len(outer)

    bm = bmesh.new()
    bot = [bm.verts.new(p) for p in outer]
    bm.verts.ensure_lookup_table()
    try:
        bm.faces.new(bot)
    except ValueError as exc:
        bm.free()
        raise RuntimeError(f"impossible de créer la face de base: {exc}") from exc

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

    if body_h > 1e-8:
        extrude_up(body_h, remove_old_cap=False)
    if bh > 1e-8:
        extrude_up(bh, remove_old_cap=True)

    top_fs = _top_faces(bm)
    top_verts = []
    seen = set()
    for f in top_fs:
        for v in f.verts:
            if v.index not in seen:
                seen.add(v.index)
                top_verts.append(v)

    matched = []
    used = set()
    for i, p in enumerate(outer):
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
            best = top_verts[i % len(top_verts)]
        used.add(best.index)
        matched.append(best)

    # Travel max (clamp silhouette) + directions
    max_travel = []
    directions = []
    for i in range(n):
        p = outer[i]
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
            if point_in_poly(Vector((cand.x, cand.y, 0.0)), outer):
                best = mid
                lo = mid
            else:
                hi = mid
        max_travel.append(best * 0.98)

    # Appliquer une première fois + léger lissage des dests
    dests = []
    for i, v in enumerate(matched):
        p = outer[i]
        d = directions[i]
        if d.length < 1e-12 or max_travel[i] < 1e-12:
            dests.append(Vector((p.x, p.y, 0.0)))
            v.co = Vector((p.x, p.y, height))
            continue
        start = Vector((p.x, p.y, body_h))
        final = start + d * max_travel[i]
        dests.append(Vector((final.x, final.y, 0.0)))
        v.co = Vector((final.x, final.y, height))
    dests = smooth_poly(dests, iters=1)
    for i, v in enumerate(matched):
        # Recalcule max_travel depuis dest lissé (projection sur direction)
        p = outer[i]
        d = directions[i]
        if d.length < 1e-12:
            continue
        # distance 3D le long de d depuis start jusqu'à (dests[i].xy, height)
        start = Vector((p.x, p.y, body_h))
        target = Vector((dests[i].x, dests[i].y, height))
        delta = target - start
        proj = max(0.0, delta.dot(d))
        max_travel[i] = min(max_travel[i], proj)
        v.co = Vector((dests[i].x, dests[i].y, height))

    # Ouvrir le haut avant résolution
    top_cap = _top_faces(bm)
    if top_cap:
        bmesh.ops.delete(bm, geom=list(top_cap), context="FACES")
    bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))

    hits_before, _tmp = find_open_mesh_crossings(bm, z_min=body_h)
    _tmp.free()
    n_before = len(hits_before)

    hits, hits_bm, n_iters, scales = resolve_crossings_by_pullback(
        bm,
        matched,
        outer,
        normals,
        max_travel=max_travel,
        directions=directions,
        height=height,
        body_h=body_h,
    )
    z_hits = [h["z"] for h in hits]
    print(
        f"[dice_maker bevel] crossings {n_before} → {len(hits)} "
        f"(iters={n_iters}, scale_min={min(scales):.3f})"
        + (
            f" residual_z=[{min(z_hits):.4f}, {max(z_hits):.4f}]"
            if z_hits
            else ""
        )
    )

    # Refermer le plateau
    close_open_top(bm, height, merge_dist=1e-4)
    # Merge un peu plus large sur le fil (bras pincés)
    top = [v for v in bm.verts if abs(v.co.z - height) < 1e-3]
    if top:
        bmesh.ops.remove_doubles(bm, verts=top, dist=5e-4)
    bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))

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
    bm2.to_mesh(result_me)
    bm2.free()

    info = {
        "mode": mode,
        "angle": float(angle),
        "distance": float(distance),
        "vert_drop": vert,
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
    height=1.0,
    angle=45.0,
    distance=0.25,
    resolution=256,
):
    """Construit le volume bevel (extrude → move → cut). Retourne (volume_obj, info)."""
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
        outer = curve_points(src, res)
        me, info = build_extrude_move_cut_mesh(
            outer,
            height=height,
            angle=angle,
            distance=distance,
        )
        volume = write_volume_object(me, names["volume"])
        hits_bm = info.pop("hits_bm", None)
        hits = info.pop("hits", None) or []
        if hits_bm is not None:
            if hits:
                write_crossings_object(hits_bm, names["crossings"])
            else:
                hits_bm.free()
                # Nettoyer un éventuel ancien objet crossings
                old = bpy.data.objects.get(names["crossings"])
                if old is not None:
                    data = old.data
                    bpy.data.objects.remove(old, do_unlink=True)
                    if data and data.users == 0:
                        bpy.data.meshes.remove(data)

        print(
            f"[dice_maker bevel] src={src.name} vol={volume.name} "
            f"mode={info['mode']} angle={info['angle']:.1f}° "
            f"dist={info['distance']:.4f} drop={info['vert_drop']:.4f} "
            f"travel_avg={info['inset_travel_avg']:.4f} "
            f"boundary={info['boundary']} nonmanifold={info['nonmanifold']} "
            f"verts={info['nverts']} "
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
    """Paramètres : extrude → move (normale+angle) → coupe boolean."""

    height: FloatProperty(
        name="Height",
        description="Hauteur totale du volume",
        default=1.0,
        min=0.01,
        max=100.0,
        subtype="DISTANCE",
    )
    angle: FloatProperty(
        name="Angle",
        description="Angle depuis l'horizontale (0=plat, 45=chanfrein) — oriente le déplacement vers le haut",
        default=45.0,
        min=0.0,
        max=89.0,
    )
    distance: FloatProperty(
        name="Distance",
        description="Longueur du déplacement le long de (normale + angle)",
        default=0.25,
        min=0.0,
        max=10.0,
        subtype="DISTANCE",
    )
    resolution: IntProperty(
        name="Resolution",
        description="Nombre de points sur le contour source",
        default=256,
        min=32,
        max=1024,
    )


class DICE_MAKER_OT_test_bevel_volume(Operator):
    """Tester le volume bevel sur la courbe active"""

    bl_idname = "dice_maker.test_bevel_volume"
    bl_label = "Build Bevel Volume"
    bl_description = (
        "Extrude corps + biseau, déplace (normale/angle/distance), coupe boolean. "
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
                height=props.height,
                angle=float(props.angle),
                distance=props.distance,
                resolution=props.resolution,
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
        col.label(text="extrude → move → resolve → close")
        col.label(text="pullback local sur crossings")
        col.label(text="Sortie: *-beveled-volume (+ crossings si residual)")
        layout.separator()

        src = context.active_object
        if src is None or src.type != "CURVE":
            box = layout.box()
            box.label(text="Sélectionne une Curve", icon="ERROR")
        else:
            layout.label(text=f"Source: {src.name}", icon="CURVE_DATA")

        layout.prop(props, "height")
        layout.prop(props, "angle")
        layout.prop(props, "distance")
        layout.prop(props, "resolution")
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
