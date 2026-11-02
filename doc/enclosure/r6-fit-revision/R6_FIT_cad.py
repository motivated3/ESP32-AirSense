"""R6 two-piece PLA fit revision, based on the failed R5 physical print.

Coordinates: rear view, X right, Y up; Z=0 is the original case rim.
The user confirms the four post tops are 1 mm above the case rim. The groove
profile remains unmeasured; geometry validation does not prove physical fit.
"""

from collections import Counter
import hashlib
import json
from pathlib import Path
import struct

import cadquery as cq


OUT = Path(__file__).resolve().parent
HOLES = [(x, y) for x in (-12, 12) for y in (-18, 18)]
PLATE_WIDTH, PLATE_HEIGHT, PLATE_RADIUS = 31.4, 39.0, 5.5
COVER_WIDTH, COVER_HEIGHT, COVER_RADIUS = 37.6, 45.2, 8.0
PLATE_BOTTOM, PLATE_TOP = -2.8, -2.0
POST_TOP, EAR_THICKNESS = 1.0, 1.2
EAR_UNDER = POST_TOP
EAR_TOP = EAR_UNDER + EAR_THICKNESS
POST_RELIEF_RADIUS = 3.0  # Open cup, instead of R5's solid lower standoff.
EAR_RADIUS = 3.8
SHAFT_RADIUS, HEAD_RADIUS = 1.2, 2.4
HEAD_SEAT = EAR_TOP + .8  # Four 0.20 mm layers under the screw head.
INNER_BACK, OUTER_BACK = 10.0, 11.4
MODULES = {
    # X, Y, X-size, Y-size, height. SCD41 PCB is 21.6 x 13.4, rotated
    # vertically to match the photographed module and make both boards fit.
    "SCD41": (0.0, 7.7, 13.4, 21.6, 9.0),
    "SFA40": (0.0, -11.2, 17.0, 15.0, 6.0),
}


def rounded(w, h, r, z0, z1):
    return (cq.Workplane("XY").rect(w, h).extrude(z1-z0)
            .edges("|Z").fillet(r).translate((0, 0, z0)).val())


def box(w, h, z0, z1, x=0, y=0):
    return (cq.Workplane("XY").box(w, h, z1-z0,
            centered=(True, True, False)).translate((x, y, z0)).val())


def cylinder(r, z0, z1, x, y):
    return (cq.Workplane("XY").circle(r).extrude(z1-z0)
            .translate((x, y, z0)).val())


def join(parts):
    result = parts[0]
    for part in parts[1:]:
        result = result.fuse(part)
    return result.clean()


def shape_report(shape):
    bb = shape.BoundingBox()
    return {"valid": shape.isValid(), "solids": len(shape.Solids()),
            "bounds_mm": [round(bb.xlen, 3), round(bb.ylen, 3), round(bb.zlen, 3)],
            "volume_mm3": round(shape.Volume(), 3)}


def stl_report(path):
    raw = path.read_bytes()
    count = struct.unpack_from("<I", raw, 80)[0]
    assert len(raw) == 84 + 50*count
    edges = Counter()
    for i in range(count):
        row = struct.unpack_from("<12fH", raw, 84 + 50*i)
        points = [tuple(round(v, 5) for v in row[j:j+3]) for j in (3, 6, 9)]
        assert len(set(points)) == 3
        for a, b in ((0, 1), (1, 2), (2, 0)):
            edges[tuple(sorted((points[a], points[b])))] += 1
    assert edges and all(n == 2 for n in edges.values()), path.name
    return {"triangles": count, "manifold": True,
            "sha256": hashlib.sha256(raw).hexdigest()}


def build_base():
    profile = rounded(PLATE_WIDTH, PLATE_HEIGHT, PLATE_RADIUS,
                      PLATE_BOTTOM-1, EAR_TOP+1)
    floor = rounded(PLATE_WIDTH, PLATE_HEIGHT, PLATE_RADIUS,
                    PLATE_BOTTOM, PLATE_TOP)
    # Clear the full original post zone under each raised bearing ear. R5 had
    # a solid 0.8 mm standoff there, which is a likely insertion obstruction.
    for x, y in HOLES:
        floor = floor.cut(cylinder(POST_RELIEF_RADIUS, PLATE_BOTTOM-.1,
                                   EAR_UNDER+.01, x, y))
    parts = [floor]
    for x, y in HOLES:
        wall = cylinder(EAR_RADIUS, PLATE_TOP-.05, EAR_UNDER+.01, x, y)
        wall = wall.cut(cylinder(POST_RELIEF_RADIUS, PLATE_BOTTOM-.1,
                                 EAR_UNDER+.02, x, y))
        roof = cylinder(EAR_RADIUS, EAR_UNDER, EAR_TOP, x, y)
        parts.extend([wall.intersect(profile), roof.intersect(profile)])
    # No central top/bottom bars: the two real board heights sum to 36.6 mm,
    # leaving only 2.4 mm vertically in this 39 mm floor. Two low U rails
    # retain each board laterally and at the far end; tape supports its back.
    for name, (x, y, w, h, _) in MODULES.items():
        rail_z1 = PLATE_TOP + 1.4
        offset = w/2 + .3 + .4
        for side in (-1, 1):
            rail = box(.8, h+.6, PLATE_TOP-.05, rail_z1,
                       x + side*offset, y)
            if side == 1:
                rail = rail.cut(box(1.1, 3.2, PLATE_TOP, rail_z1+.1,
                                    x+offset, 6.5 if name == "SCD41" else -11.2))
            parts.append(rail.intersect(profile))
        far_y = y + (h/2+.7)*(1 if name == "SCD41" else -1)
        parts.append(box(w+1.8, .8, PLATE_TOP-.05, rail_z1, x, far_y)
                     .intersect(profile))
    base = join(parts)
    # BAT socket relief doubles as the only entry for four fine sensor wires.
    base = base.cut(box(12.5, 6.8, PLATE_BOTTOM-.1, EAR_TOP+1, 13.75, -2.8))
    for x, y, w, h, height in MODULES.values():
        # The SFA40 board passes close to both lower bearing ears. Relieve
        # only their inward edge above the floor, keeping the screw land.
        base = base.cut(box(w+.6, h+.6, -1.5, -1.3+height+.2, x, y))
    for x, y in HOLES:
        base = base.cut(cylinder(SHAFT_RADIUS, PLATE_BOTTOM-.1, EAR_TOP+1, x, y))
    return base.clean()


def build_cover():
    outer = rounded(COVER_WIDTH, COVER_HEIGHT, COVER_RADIUS, 0, OUTER_BACK)
    inner = rounded(COVER_WIDTH-2.8, COVER_HEIGHT-2.8,
                    COVER_RADIUS-1.4, -.1, INNER_BACK)
    cover = outer.cut(inner)
    feet = []
    for x, y in HOLES:
        # Contact sits at post top + ear thickness, 2.2 mm above the rim.
        # Preserve the narrow first 1.4 mm of the foot below its wide collar.
        foot = cylinder(2.9, EAR_TOP, INNER_BACK+.02, x, y)
        collar = cylinder(3.5, EAR_TOP+1.4, INNER_BACK+.02, x, y)
        for mx, my, w, h, mh in MODULES.values():
            keepout = box(w+1.2, h+1.2, PLATE_TOP, -1.3+mh+.6, mx, my)
            collar = collar.cut(keepout)
        feet.extend([foot, collar])
    cover = join([cover]+feet)
    for x, y in HOLES:
        cover = cover.cut(cylinder(SHAFT_RADIUS, -.1, OUTER_BACK+.1, x, y))
        cover = cover.cut(cylinder(HEAD_RADIUS, HEAD_SEAT,
                                   OUTER_BACK+.1, x, y))
    for y, width in ((8.0, 11.0), (-11.2, 12.5)):
        for offset in (-4, -2, 0, 2, 4):
            cover = cover.cut(box(width, .9, INNER_BACK-.1,
                                  OUTER_BACK+.1, 0, y+offset))
    for side in (-1, 1):
        for y, length in ((7.7, 10), (-11.2, 7)):
            for z in (3.1, 5.3, 7.5):
                cover = cover.cut(box(4, length, z-.45, z+.45,
                                      side*COVER_WIDTH/2, y))
    # Retain R5's small acoustic holes, without claiming alignment to the
    # original front-shell speaker and microphone.
    for dx, dy in ((0, 0), (-1.9, 0), (1.9, 0), (0, -1.9), (0, 1.9)):
        cover = cover.cut(cylinder(.65, INNER_BACK-.1,
                                   OUTER_BACK+.1, 12.1+dx, 8+dy))
    cover = cover.cut(cylinder(.8, INNER_BACK-.1,
                               OUTER_BACK+.1, 12.1, -10.5))
    return cover.clean()


def main():
    base, cover = build_base(), build_cover()
    report = {
        "stage": "R6 complete PLA fit revision; physical fit unverified",
        "fit_ready": False,
        "basis": "R5 failure photos; SCD41 PCB 21.6x13.4 mm and post tops 1 mm above the case rim confirmed by user",
        "changes": {
            "scd41_xy_mm": [13.4, 21.6],
            "scd41_rail_inside_width_mm": 14.0,
            "scd41_pcb_length_mm": 21.6,
            "base_outer_xy_mm": [PLATE_WIDTH, PLATE_HEIGHT],
            "base_corner_radius_mm": PLATE_RADIUS,
            "base_floor_thickness_mm": PLATE_TOP-PLATE_BOTTOM,
            "post_relief_diameter_mm": 2*POST_RELIEF_RADIUS,
            "ear_roof_thickness_mm": EAR_TOP-EAR_UNDER,
            "original_post_top_z_mm": POST_TOP,
            "ear_under_z_mm": EAR_UNDER,
            "ear_top_z_mm": EAR_TOP,
            "cover_foot_contact_z_mm": EAR_TOP,
            "cover_foot_setback_from_rim_mm": EAR_TOP,
            "screw_head_seat_z_mm": HEAD_SEAT,
            "screw_head_bearing_floor_mm": HEAD_SEAT-EAR_TOP,
            "head_seat_to_post_top_mm": HEAD_SEAT-POST_TOP,
            "cover_outer_xy_mm": [COVER_WIDTH, COVER_HEIGHT],
            "cover_corner_radius_mm": COVER_RADIUS,
            "cover_min_z_mm": 0,
            "hole_spacing_xy_mm": [24, 36],
        },
        "parts": {"baseplate": shape_report(base),
                  "cover": shape_report(cover)},
        "module_check": {},
        "hole_check": [],
    }
    assert all(v["valid"] and v["solids"] == 1 for v in report["parts"].values())
    assert base.intersect(cover).Volume() < 1e-5
    assert base.BoundingBox().xlen <= PLATE_WIDTH+.01
    assert base.BoundingBox().ylen <= PLATE_HEIGHT+.01
    assert cover.BoundingBox().zmin >= -1e-5
    assert abs(EAR_UNDER-POST_TOP) < 1e-9
    assert abs(EAR_TOP-POST_TOP-1.2) < 1e-9
    for name, (x, y, w, h, height) in MODULES.items():
        body = box(w, h, -1.3, -1.3+height, x, y)
        result = {"pcb_xy_mm": [w, h],
                  "base_overlap_mm3": round(body.intersect(base).Volume(), 6),
                  "cover_overlap_mm3": round(body.intersect(cover).Volume(), 6),
                  "inside_cover_clearance_mm": round(body.distance(cover), 3)}
        assert result["base_overlap_mm3"] < 1e-5, name
        assert result["cover_overlap_mm3"] < 1e-5, name
        report["module_check"][name] = result
    for x, y in HOLES:
        shaft = cylinder(SHAFT_RADIUS*.95, PLATE_BOTTOM-.1, OUTER_BACK+.1, x, y)
        foot_slice = cover.intersect(cylinder(2.9, EAR_TOP+.1, EAR_TOP+.2, x, y))
        ear_slice = base.intersect(cylinder(2.9, EAR_TOP-.1, EAR_TOP, x, y))
        original_post = cylinder(2.1, PLATE_BOTTOM-1, POST_TOP, x, y)
        seat = cylinder(HEAD_RADIUS, HEAD_SEAT-.1, HEAD_SEAT, x, y).cut(
            cylinder(SHAFT_RADIUS, HEAD_SEAT-.2, HEAD_SEAT+.1, x, y))
        result = {"xy_mm": [x, y],
                  "shaft_blocked_mm3": round(
                      shaft.intersect(base).Volume()+shaft.intersect(cover).Volume(), 6),
                  "ear_roof_area_mm2": round(base.intersect(
                      cylinder(3.8, EAR_UNDER+.6, EAR_UNDER+.7, x, y)).Volume()/.1, 3),
                  "cover_foot_area_mm2": round(foot_slice.Volume()/.1, 3),
                  "foot_ear_contact_area_mm2": round(
                      ear_slice.translate((0, 0, .2)).intersect(foot_slice).Volume()/.1, 3),
                  "actual_cover_foot_min_z_mm": round(cover.intersect(
                      cylinder(2.85, 0, INNER_BACK, x, y)).BoundingBox().zmin, 6),
                  "cover_column_below_contact_mm3": round(cover.intersect(
                      cylinder(2.9, -.1, EAR_TOP, x, y)).Volume(), 6),
                  "assumed_d4p2_post_base_overlap_mm3": round(
                      original_post.intersect(base).Volume(), 6),
                  "screw_head_bearing_area_mm2": round(seat.intersect(cover).Volume()/.1, 3)}
        assert result["shaft_blocked_mm3"] < 1e-5
        assert result["ear_roof_area_mm2"] > 5
        assert result["cover_foot_area_mm2"] > 5
        assert result["foot_ear_contact_area_mm2"] > 10
        assert abs(result["actual_cover_foot_min_z_mm"]-EAR_TOP) < 1e-5
        assert result["cover_column_below_contact_mm3"] < 1e-5
        assert result["assumed_d4p2_post_base_overlap_mm3"] < 1e-5
        assert result["screw_head_bearing_area_mm2"] > 10
        report["hole_check"].append(result)
    for name, shape in (("baseplate", base), ("cover", cover)):
        cq.exporters.export(shape, str(OUT/f"R6_FIT_{name}.step"))
        path = OUT/f"R6_FIT_{name}.stl"
        cq.exporters.export(shape, str(path), tolerance=.06, angularTolerance=.12)
        roundtrip = cq.importers.importStep(str(OUT/f"R6_FIT_{name}.step")).val()
        assert roundtrip.isValid() and len(roundtrip.Solids()) == 1
        assert abs(roundtrip.Volume()-shape.Volume()) < .001
        report["parts"][name]["stl"] = stl_report(path)
    (OUT/"R6_FIT_geometry-check.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2)+"\n")
    print(json.dumps({"parts": report["parts"],
                      "module_check": report["module_check"]},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
