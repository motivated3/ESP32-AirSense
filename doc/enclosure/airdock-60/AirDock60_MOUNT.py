"""Vented AirDock60 backing with a front mating rim on the fitted R8.

Local axes are portrait rear view: X right, Y up, Z rearward from the rim.
Existing soldered wires use the bottom-open U-slot added by AirDock60_CAD.py.
"""
from functools import lru_cache
from pathlib import Path
import hashlib
import importlib.util
import math
import cadquery as cq
from OCP.gp import gp_Trsf

HERE = Path(__file__).resolve().parent
ENCLOSURE = HERE.parent
WIDTH, HEIGHT, RADIUS = 37.6, 45.2, 8.0
BACK, INNER = 3.4, 2.2
HEAD_SEAT, FOOT_CONTACT = 3.0, INNER
THICKNESS = BACK - INNER
RIM_DEPTH = .8
RIM_FRONT = INNER - RIM_DEPTH
VENT_X = (-10.5, -7.5, -4.5, -1.5, 1.5, 4.5, 7.5, 10.5)
VENT_Y, VENT_LENGTH, VENT_WIDTH = 7.0, 14.0, 1.4
HOLES = tuple((x, y) for x in (-12.0, 12.0) for y in (-18.0, 18.0))
SHAFT_RADIUS = 1.2
ANGLE, TILT = 60.0, 30.0
# Fixed assembly datum: do NOT recalculate from the thinner BACK value.
LIFT = 2.9
_REFERENCES = (ENCLOSURE / "r8-wide-base/R8_BASE.step",
               ENCLOSURE / "r8-wide-base/R8_BASE.stl")


def _reference_hashes():
    return {str(p.relative_to(ENCLOSURE)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in _REFERENCES}


_REFERENCE_SHA256 = _reference_hashes()

spec = importlib.util.spec_from_file_location('airdock60_lip_reference',
    ENCLOSURE/'r11-locating-lip/R11_COVER_cad.py')
lip = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lip)
LIP_SEGMENTS = [dict(item, range=[-8,-3]) if item['name']=='bottom_center'
                else dict(item) for item in lip.SEGMENTS]


@lru_cache(maxsize=1)
def _old_base():
    return cq.importers.importStep(str(_REFERENCES[0])).val()


def _box(w, h, z0, z1, x=0, y=0):
    return (cq.Workplane("XY").box(w, h, z1-z0, centered=(True, True, False))
            .translate((x, y, z0)).val())


def _cylinder(radius, z0, z1, x, y):
    return (cq.Workplane("XY").center(x, y).circle(radius).extrude(z1-z0)
            .translate((0, 0, z0)).val())


def build_mount_local() -> cq.Shape:
    plate = (cq.Workplane("XY").rect(WIDTH, HEIGHT).extrude(THICKNESS)
             .edges("|Z").fillet(RADIUS).translate((0, 0, INNER)).val())
    for x, y in HOLES:
        plate = plate.cut(_cylinder(SHAFT_RADIUS, INNER-.1, BACK+.1, x, y))
        # Only the four head seats stay at q=3.0, preserving the original
        # screw engagement despite increasing the general plate thickness.
        plate = plate.cut(_cylinder(2.4, HEAD_SEAT, BACK+.1, x, y))
    for x in VENT_X:
        vent = (cq.Workplane('XY').center(x, VENT_Y)
                .slot2D(VENT_LENGTH, VENT_WIDTH, 90).extrude(THICKNESS+.2)
                .translate((0,0,INNER-.1)).val())
        plate = plate.cut(vent)
    # Per the user's red dimension, this rim projects only 0.8 mm from
    # the plate underside. Do not substitute the old q=0 joint datum.
    rim = lip.r6.rounded(WIDTH, HEIGHT, RADIUS, RIM_FRONT, INNER+.05).cut(
        lip.r6.rounded(34.8, 42.4, 6.6, RIM_FRONT-.1, INNER+.1))
    plate = plate.fuse(rim)
    for definition in LIP_SEGMENTS:
        plate = plate.fuse(lip.lip_segment(definition)[0].translate((0,0,RIM_FRONT)))
    return plate.clean()


def to_world(shape: cq.Shape) -> cq.Shape:
    """Map X=-Xold, D=Zold, Z=Yold+22.6; lean back 30 degrees; add fixed lift."""
    s, c = math.sin(math.radians(TILT)), math.cos(math.radians(TILT))
    transform = gp_Trsf()
    transform.SetValues(-1, 0, 0, 0,
                        0, s, c, 22.6*s,
                        0, c, -s, 22.6*c+LIFT)
    return shape.moved(cq.Location(transform))


def verify_mount_local(shape: cq.Shape) -> dict:
    assert _reference_hashes() == _REFERENCE_SHA256, "A fitted R8 reference changed"
    assert shape.isValid() and len(shape.Solids()) == 1
    original = shape
    # OCC boolean diagnostics may adjust operands; keep caller/reference copies.
    plate, base = shape.copy(), _old_base().copy()
    bb = plate.BoundingBox()
    assert all(abs(a-b) < 1e-5 for a, b in zip(
        (bb.xlen, bb.ylen, bb.zmin, bb.zmax), (WIDTH, HEIGHT, RIM_FRONT-.8, BACK)))
    overlap = plate.intersect(base).Volume()
    former_bat_patch = _box(8, 4, INNER, BACK, 13, -2.8)
    missing_patch = former_bat_patch.cut(plate).Volume()
    assert max(overlap, missing_patch) < 1e-5
    screws = []
    for x, y in HOLES:
        shaft = plate.intersect(_cylinder(SHAFT_RADIUS, INNER-.1, BACK+.1, x, y)).Volume()
        seat = _cylinder(2.4, INNER, HEAD_SEAT, x, y).cut(
            _cylinder(SHAFT_RADIUS, INNER-.1, BACK+.1, x, y))
        missing_seat = seat.cut(plate).Volume()
        above = plate.intersect(_cylinder(2.4, HEAD_SEAT+1e-5, BACK+3, x, y)).Volume()
        below = plate.intersect(_cylinder(2.6, 0, INNER-1e-5, x, y)).Volume()
        old_contact = base.intersect(_cylinder(2.6, INNER-.01, INNER, x, y))
        contact = old_contact.translate((0, 0, .01)).intersect(plate).Volume()/.01
        assert max(shaft, missing_seat, above, below) < 1e-5 and contact > 10, (x,y,shaft,missing_seat,above,below,contact)
        screws.append({"local_xy_mm": [x, y], "shaft_obstruction_mm3": shaft,
                       "missing_bearing_plate_mm3": missing_seat,
                       "material_above_flat_head_seat_mm3": above,
                       "material_below_flat_plate_mm3": below,
                       "head_bearing_z_mm": HEAD_SEAT, "plate_underside_z_mm": FOOT_CONTACT,
                       "R8_ear_contact_area_mm2": contact})
    assert original.isValid() and to_world(original).isValid()
    assert _reference_hashes() == _REFERENCE_SHA256
    return {
        "valid_single_solid": True,
        "design": "1.2 mm vented backing; original screw seats, front mating rim and six reused locating lips",
        "local_bounds_mm": [bb.xlen, bb.ylen, bb.zmin, bb.zmax],
        "normal_plate_thickness_mm": THICKNESS,
        "legacy_post_reference_z_mm": 1.0,
        "user_reported_post_to_rim_step_mm": .8,
        "interface_note": "User specifies 1.2 mm plate plus 0.8 mm rim. Keep fitted R8 and four screw seats; rim front is q=1.4, independent of the old q=0 reference. Shell-side fit still requires a physical check.",
        "retained_R8_ear_under_top_z_mm": [1.0, 2.2],
        "retained_R8_ear_thickness_mm": 1.2,
        "head_bearing_plane_z_mm": HEAD_SEAT,
        "original_screw_heads_exposed": True,
        "head_seat_relief_depth_mm": BACK-HEAD_SEAT,
        "mating_rim_q_mm": [RIM_FRONT, INNER],
        "mating_rim_projection_mm": RIM_DEPTH,
        "red_edge_total_thickness_mm": THICKNESS+RIM_DEPTH,
        "locating_lip_count": len(LIP_SEGMENTS),
        "bottom_lip_note": "Shifted to X=-8..-3 to keep the bottom-open soldered-wire entry unobstructed.",
        "lip_insertion_mm": lip.INSERTION,
        "backing_vent_count": len(VENT_X),
        "complete_R8_intersection_mm3": overlap,
        "R8_minimum_distance_mm": plate.distance(base),
        "R8_distance_note": "Zero is intended contact with retained R8 ear tops.",
        "screws": screws,
        "new_plate_BAT_notch_removed": True,
        "former_BAT_patch_missing_mm3": missing_patch,
        "wire_installation": "Lay existing soldered wires into the bottom-open U-slot from AirDock60_CAD; no closed cable hole. The reused R8 is unchanged.",
        "world_assembly_lift_fixed_mm": LIFT,
        "references_sha256": dict(_REFERENCE_SHA256),
        "reference_files_unchanged": True,
        "physical_fit_verified": False,
        "remaining_checks": "Original front-shell inner CAD and BAT-to-plate height are unmeasured. Reused lip geometry and the new rim still require physical fit checks. The 1.2 mm plate, original screw seats and reinforced lower dock require strength and temperature tests. R8 stays unchanged.",
    }
