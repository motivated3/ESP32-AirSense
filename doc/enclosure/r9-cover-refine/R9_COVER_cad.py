"""Small exterior refinement of the fitted R6 cover; reuse the fitted R8 base.

All dimensions are mm in the original case-rim coordinate system.  Original
STEP/STL files are read-only references. This script never starts a print.
"""
import importlib.util
import json
import math
from pathlib import Path
import xml.etree.ElementTree as ET
from zipfile import ZipFile, ZIP_DEFLATED

import cadquery as cq

OUT = Path(__file__).resolve().parent
REFERENCE = OUT.parent / "r6-fit-revision"
spec = importlib.util.spec_from_file_location("r6_cover_reference", REFERENCE / "R6_FIT_cad.py")
r6 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r6)

TAPER_START = 1.2
SIDE_INSET = .4
BACK_EDGE_RADIUS = .6
SLOT_WIDTH = .9
# A capsule loses (1-pi/4)*width^2 relative to its bounding rectangle.
# Extend its length by that loss/width to preserve each original opening area.
SLOT_EXTENSION = SLOT_WIDTH * (1-math.pi/4)


def outline(w, h, r, z):
    solid = r6.rounded(w, h, r, 0, 1)
    return cq.Workplane(obj=solid).faces(">Z").val().outerWire().translate((0, 0, z-1))


def outer_body():
    w, h, r = r6.COVER_WIDTH, r6.COVER_HEIGHT, r6.COVER_RADIUS
    outer = cq.Solid.makeLoft([
        outline(w, h, r, 0), outline(w, h, r, TAPER_START),
        outline(w-2*SIDE_INSET, h-2*SIDE_INSET, r-SIDE_INSET, r6.OUTER_BACK),
    ], ruled=True)
    # Round only the outer rear perimeter before cutting the inner cavity,
    # screw wells, vents or acoustic holes. The mating rim is untouched.
    return cq.Workplane(obj=outer).edges(">Z").fillet(BACK_EDGE_RADIUS).val()


def slot_on_back(length, y):
    return (cq.Workplane("XY").center(0, y)
            .slot2D(length+SLOT_EXTENSION, SLOT_WIDTH)
            .extrude(r6.OUTER_BACK-r6.INNER_BACK+.2)
            .translate((0, 0, r6.INNER_BACK-.1)).val())


def slot_on_side(length, y, z, side):
    return (cq.Workplane("YZ").center(y, z)
            .slot2D(length+SLOT_EXTENSION, SLOT_WIDTH)
            .extrude(4).translate((side*r6.COVER_WIDTH/2-2, 0, 0)).val())


def build_cover():
    inner = r6.rounded(r6.COVER_WIDTH-2.8, r6.COVER_HEIGHT-2.8,
                       r6.COVER_RADIUS-1.4, -.1, r6.INNER_BACK)
    cover = outer_body().cut(inner)
    # Retain the exact fitted screw feet and reinforcement geometry.
    feet = []
    for x, y in r6.HOLES:
        foot = r6.cylinder(2.9, r6.EAR_TOP, r6.INNER_BACK+.02, x, y)
        collar = r6.cylinder(3.5, r6.EAR_TOP+1.4, r6.INNER_BACK+.02, x, y)
        for mx, my, w, h, height in r6.MODULES.values():
            collar = collar.cut(r6.box(w+1.2, h+1.2, r6.PLATE_TOP,
                                      -1.3+height+.6, mx, my))
        feet.extend([foot, collar])
    cover = r6.join([cover]+feet)
    for x, y in r6.HOLES:
        cover = cover.cut(r6.cylinder(r6.SHAFT_RADIUS, -.1, r6.OUTER_BACK+.1, x, y))
        cover = cover.cut(r6.cylinder(r6.HEAD_RADIUS, r6.HEAD_SEAT,
                                     r6.OUTER_BACK+.1, x, y))
    for y, length in ((8.0, 11.0), (-11.2, 12.5)):
        for offset in (-4, -2, 0, 2, 4):
            cover = cover.cut(slot_on_back(length, y+offset))
    for side in (-1, 1):
        for y, length in ((7.7, 10), (-11.2, 7)):
            for z in (3.1, 5.3, 7.5):
                cover = cover.cut(slot_on_side(length, y, z, side))
    for dx, dy in ((0, 0), (-1.9, 0), (1.9, 0), (0, -1.9), (0, 1.9)):
        cover = cover.cut(r6.cylinder(.65, r6.INNER_BACK-.1,
                                     r6.OUTER_BACK+.1, 12.1+dx, 8+dy))
    cover = cover.cut(r6.cylinder(.8, r6.INNER_BACK-.1,
                                 r6.OUTER_BACK+.1, 12.1, -10.5))
    return cover.clean()


def symmetric_difference(a, b):
    return a.cut(b).Volume()+b.cut(a).Volume()


def package_print_mesh(stl):
    spec = importlib.util.spec_from_file_location("r6_mesh_pack", REFERENCE/"R6_FIT_pack_3mf.py")
    pack = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pack)
    vertices, triangles, report = pack.read_binary_stl(stl)
    vertices = [(x, -y, r6.OUTER_BACK-z) for x, y, z in vertices]
    assert abs(min(z for _, _, z in vertices)) < 1e-5
    model = ET.Element(f"{{{pack.NS}}}model", {"unit": "millimeter"})
    pack.node(model, "metadata", name="Title").text = "R9 refined cover only: tapered rear, rounded grilles"
    resources, build = pack.node(model, "resources"), pack.node(model, "build")
    obj = pack.node(resources, "object", id=1, type="model", name="R9_COVER_ONLY")
    mesh = pack.node(obj, "mesh")
    vs, ts = pack.node(mesh, "vertices"), pack.node(mesh, "triangles")
    for x, y, z in vertices:
        pack.node(vs, "vertex", x=f"{x:.5f}", y=f"{y:.5f}", z=f"{z:.5f}")
    for a, b, c in triangles:
        pack.node(ts, "triangle", v1=a, v2=b, v3=c)
    pack.node(build, "item", objectid=1, transform="1 0 0 0 1 0 0 0 1 130 130 0")
    target = OUT/"R9_COVER_geometry.3mf"
    with ZipFile(REFERENCE/"R6_POST1mm_CONTACT2p2mm.3mf") as source:
        with ZipFile(target, "w", ZIP_DEFLATED) as archive:
            for name in ("[Content_Types].xml", "_rels/.rels"):
                archive.writestr(name, source.read(name))
            archive.writestr("3D/3dmodel.model", ET.tostring(model, encoding="utf-8", xml_declaration=True))
    with ZipFile(target) as archive:
        assert archive.testzip() is None
    return {"file": target.name, "objects": 1, "interior_facing_up": True,
            "mesh": report, "toolpaths_included": False}


def verify(cover, old, base):
    assert cover.isValid() and len(cover.Solids()) == 1
    assert base.intersect(cover).Volume() < 1e-5
    bb = cover.BoundingBox()
    assert abs(bb.zmin) < 1e-6 and abs(bb.zmax-r6.OUTER_BACK) < 1e-6
    assert abs(bb.xlen-r6.COVER_WIDTH) < 1e-6
    assert abs(bb.ylen-r6.COVER_HEIGHT) < 1e-6

    rim = r6.box(100, 100, 0, TAPER_START)
    rim_delta = symmetric_difference(cover.intersect(rim), old.intersect(rim))
    assert rim_delta < 1e-5
    # Cover material newly inside the original main cavity must remain zero;
    # equal-area rounded slots necessarily refill tiny former slot corners.
    cavity = r6.rounded(r6.COVER_WIDTH-2.8, r6.COVER_HEIGHT-2.8,
                        r6.COVER_RADIUS-1.4, -.1, r6.INNER_BACK)
    cavity_delta = cover.cut(old).intersect(cavity).Volume()
    assert cavity_delta < 1e-5
    screw_checks = []
    for x, y in r6.HOLES:
        # Capture the complete bearing floor, the narrow lower foot and the
        # complete round collar without including the exterior styling skin.
        region = r6.cylinder(3.5, r6.EAR_TOP, r6.INNER_BACK, x, y)
        delta = symmetric_difference(cover.intersect(region), old.intersect(region))
        assert delta < 1e-5
        low = r6.cylinder(3.5, r6.EAR_TOP, r6.EAR_TOP+1.4, x, y)
        assert symmetric_difference(cover.intersect(low), old.intersect(low)) < 1e-5
        shaft = r6.cylinder(1.19, 0, r6.OUTER_BACK+.1, x, y)
        assert cover.intersect(shaft).Volume() < 1e-5
        seat = r6.cylinder(2.39, r6.HEAD_SEAT+.001, r6.OUTER_BACK+.1, x, y)
        assert cover.intersect(seat).Volume() < 1e-5
        screw_checks.append({"center_xy": [x, y], "lower_foot_and_seat_delta_mm3": delta})

    # Minimum wall of the straight and rounded side outline at the cavity
    # ceiling, where the full 10 mm-high cavity is still present.
    outer_section = outer_body().intersect(r6.box(100, 100, 9.999, 10.0))
    inner_section = cavity.intersect(r6.box(100, 100, 9.999, 10.0))
    outer_wires = cq.Workplane(obj=outer_section).faces(">Z").val().outerWire()
    inner_wires = cq.Workplane(obj=inner_section).faces(">Z").val().outerWire()
    side_wall = outer_wires.distance(inner_wires)
    assert side_wall >= 1.0
    # At the flat back surface the fillet is at its deepest inward extent.
    back_face = cq.Workplane(obj=outer_body()).faces(">Z").val()
    well_walls = []
    for x, y in r6.HOLES:
        circle = cq.Workplane("XY").circle(r6.HEAD_RADIUS).val().translate((x, y, r6.OUTER_BACK))
        thickness = circle.distance(back_face.outerWire())
        assert thickness >= 1.0
        well_walls.append(thickness)

    module_checks = {}
    # Keep the existing conservative R8 envelope in addition to the user's
    # >3 mm real-world top clearance; never substitute the latter into CAD.
    for name, (x, y, w, h, height) in r6.MODULES.items():
        body = r6.box(w, h, .2, .2+height, x, y)
        overlap = body.intersect(cover).Volume()
        assert overlap < 1e-5
        module_checks[name] = {"overlap_mm3": overlap, "distance_mm": body.distance(cover)}
    apertures = [{"location": site, "old_length_mm": length,
                  "new_length_mm": length+SLOT_EXTENSION, "width_mm": SLOT_WIDTH,
                  "old_area_mm2": length*SLOT_WIDTH,
                  "new_area_mm2": (length+SLOT_EXTENSION)*SLOT_WIDTH
                                  -(1-math.pi/4)*SLOT_WIDTH**2}
                 for site, length in (("back_SCD41",11), ("back_SFA40",12.5),
                                      ("side_SCD41",10), ("side_SFA40",7))]
    assert all(row["new_area_mm2"] >= row["old_area_mm2"]-1e-9 for row in apertures)
    return {"valid_single_solid": True, "mating_rim_delta_mm3": rim_delta,
            "r8_base_overlap_mm3": base.intersect(cover).Volume(),
            "new_material_inside_original_cavity_mm3": cavity_delta,
            "side_wall_at_cavity_ceiling_mm": side_wall,
            "back_screw_well_to_outer_outline_mm": well_walls,
            "screws": screw_checks, "modules": module_checks, "apertures": apertures}


def main():
    frozen = [REFERENCE/"R6_FIT_cover.step", REFERENCE/"R6_FIT_cover.stl",
              OUT.parent/"r8-wide-base/R8_BASE.step", OUT.parent/"r8-wide-base/R8_BASE.stl"]
    import hashlib
    hashes = {str(path.relative_to(OUT.parent)): hashlib.sha256(path.read_bytes()).hexdigest()
              for path in frozen}
    old = cq.importers.importStep(str(frozen[0])).val()
    base = cq.importers.importStep(str(frozen[2])).val()
    cover = build_cover()
    report = verify(cover, old, base)
    geometry = r6.shape_report(cover)  # Before export attaches triangulation tolerances.
    cq.exporters.export(cover, str(OUT/"R9_COVER.step"))
    cq.exporters.export(cover, str(OUT/"R9_COVER.stl"), tolerance=.015, angularTolerance=.08)
    reloaded = cq.importers.importStep(str(OUT/"R9_COVER.step")).val()
    assert symmetric_difference(cover, reloaded) < 1e-4
    report.update({"geometry": geometry, "mesh": r6.stl_report(OUT/"R9_COVER.stl"),
                   "geometry_package": package_print_mesh(OUT/"R9_COVER.stl"),
                   "parameters": {"side_inset_per_edge_mm": SIDE_INSET,
                                  "straight_mating_band_mm": TAPER_START,
                                  "rear_edge_fillet_mm": BACK_EDGE_RADIUS,
                                  "unchanged_cavity_ceiling_z_mm": r6.INNER_BACK,
                                  "unchanged_overall_height_mm": r6.OUTER_BACK},
                   "references_sha256": hashes,
                   "physical_evidence": "User confirms R8 base fit; actual SCD41-to-grille clearance exceeds 3 mm.",
                   "new_cover_physically_tested": False})
    assert hashes == {str(path.relative_to(OUT.parent)): hashlib.sha256(path.read_bytes()).hexdigest()
                      for path in frozen}
    (OUT/"R9_COVER_check.json").write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
