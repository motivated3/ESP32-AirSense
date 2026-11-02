"""R10 rounded rear cover: variable exterior fillet and R0.5 inner cove.

Keep the fitted R9 0.4 mm/side taper and R8 base. Geometry validation only; printing projects are packaged separately.
No physical-fit claim or print action. Reuses the current repository's R9/R6 CAD
helpers without modifying those references.
"""
from pathlib import Path
import hashlib
import importlib.util
import json

import cadquery as cq
from OCP.BRepFilletAPI import BRepFilletAPI_MakeFillet
from OCP.TColgp import TColgp_Array1OfPnt2d
from OCP.gp import gp_Pnt2d

OUT = Path(__file__).resolve().parent
ENCLOSURE = OUT.parent
spec = importlib.util.spec_from_file_location('r9_preview_reference', ENCLOSURE/'r9-cover-refine/R9_COVER_cad.py')
r9 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r9)
r6 = r9.r6
INNER_RADIUS = .5
RADIUS_LAW = [(0, .6), (.2, 1.2), (.5, 1.2), (.8, 1.2), (1, .6)]


def outer_body():
    assert r9.SIDE_INSET == .4 and r9.TAPER_START == 1.2
    w, h, r = r6.COVER_WIDTH, r6.COVER_HEIGHT, r6.COVER_RADIUS
    raw = cq.Solid.makeLoft([
        r9.outline(w, h, r, 0), r9.outline(w, h, r, r9.TAPER_START),
        r9.outline(w-.8, h-.8, r-.4, r6.OUTER_BACK)], ruled=True)
    builder = BRepFilletAPI_MakeFillet(raw.wrapped)
    builder.Add(.6, cq.Workplane(obj=raw).faces('>Z').val().Edges()[0].wrapped)
    assert builder.NbContours() == 1 and builder.NbEdges(1) == 8
    edge_types = []
    for i in range(1, builder.NbEdges(1)+1):
        edge = cq.Edge(builder.Edge(1, i))
        edge_types.append(edge.geomType())
        if edge.geomType() == 'LINE':
            law = TColgp_Array1OfPnt2d(1, len(RADIUS_LAW))
            for j, (u, radius) in enumerate(RADIUS_LAW, 1):
                law.SetValue(j, gp_Pnt2d(u, radius))
            builder.SetRadius(law, 1, i)
        else:
            assert edge.geomType() == 'CIRCLE'
            builder.SetRadius(.6, 1, i)
    assert edge_types.count('LINE') == edge_types.count('CIRCLE') == 4
    builder.Build()
    assert builder.IsDone()
    return cq.Shape.cast(builder.Shape())


def difference(a, b):
    return a.cut(b).Volume()+b.cut(a).Volume()


def main():
    paths = [ENCLOSURE/'r9-cover-refine/R9_COVER.step',
             ENCLOSURE/'r8-wide-base/R8_BASE.step',
             ENCLOSURE/'r9-cover-refine/R9_COVER_cad.py']
    hashes = {str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    old, base = (cq.importers.importStep(str(p)).val() for p in paths[:2])
    plain_rounded = r6.rounded
    original_cavity = plain_rounded(34.8, 42.4, 6.6, -.1, 10)
    rounded_cavity = cq.Workplane(obj=original_cavity).edges('>Z').fillet(INNER_RADIUS).val()
    inner_cove = original_cavity.cut(rounded_cavity)
    outer = outer_body()
    # Narrow injection points retain the exact existing screw and vent code.
    def rounded_with_inner_cove(w, h, r, z0, z1):
        if abs(w-34.8) < 1e-8 and abs(h-42.4) < 1e-8 and z1 == 10:
            return rounded_cavity
        return plain_rounded(w, h, r, z0, z1)
    r6.rounded, original_outer = rounded_with_inner_cove, r9.outer_body
    r9.outer_body = lambda: outer
    try:
        cover = r9.build_cover()
    finally:
        r6.rounded, r9.outer_body = plain_rounded, original_outer
    assert cover.isValid() and len(cover.Solids()) == 1
    assert base.intersect(cover).Volume() < 1e-5
    mating = r6.box(100, 100, 0, 1.2)
    rim_delta = difference(cover.intersect(mating), old.intersect(mating))
    assert rim_delta < 1e-5
    columns = []
    for x, y in r6.HOLES:
        region = r6.cylinder(3.5, 2.2, 11.4, x, y)
        fixed_delta = difference(cover.intersect(region), old.intersect(region))
        shaft = cover.intersect(r6.cylinder(1.2, -.1, 11.5, x, y)).Volume()
        head = cover.intersect(r6.cylinder(2.4, 3.001, 11.5, x, y)).Volume()
        assert fixed_delta < 1e-5 and shaft < 1e-5 and head < 1e-5
        columns.append({'xy_mm':[x,y], 'R3p5_fixed_region_delta_mm3':fixed_delta,
                        'shaft_obstruction_mm3':shaft, 'head_obstruction_mm3':head})
    sensors = {}
    for name, (x, y, w, h, height) in r6.MODULES.items():
        body = r6.box(w, h, .2, .2+height, x, y)
        overlap = body.intersect(cover).Volume()
        assert overlap < 1e-5
        sensors[name] = {'overlap_mm3':overlap, 'distance_mm':body.distance(cover)}
    added = cover.cut(old)
    added_outside_cove = added.cut(inner_cove).Volume()
    assert added_outside_cove < 1e-4
    sections = []
    for z in (9.49, 9.5, 9.52, 9.75, 9.99, 10):
        slab = r6.box(100, 100, z-.001, z)
        outside = cq.Workplane(obj=outer.intersect(slab)).faces('>Z').val().outerWire()
        inside = cq.Workplane(obj=rounded_cavity.intersect(slab)).faces('>Z').val().outerWire()
        thickness = outside.distance(inside)
        assert thickness >= 1.0
        sections.append({'z_mm':z, 'horizontal_outer_to_inner_outline_mm':thickness})
    rear = cq.Workplane(obj=outer).faces('>Z').val()
    wells = [cq.Workplane('XY').circle(2.4).val().translate((x,y,11.4)).distance(rear.outerWire())
             for x,y in r6.HOLES]
    assert min(wells) >= 1.0
    # Actual slot sections are well clear of the changed fillet perimeter.
    vents = []
    for yc, length in ((8,11),(-11.2,12.5)):
        for offset in (-4,-2,0,2,4):
            region = r6.box(length+1, .98, 10.7, 10.71, 0, yc+offset)
            area = region.cut(cover).Volume()/.01
            assert abs(area-length*.9) < 1e-5
            vents.append({'kind':'back','center_y_mm':yc+offset,'area_mm2':area})
    for side in (-1,1):
        for yc, length in ((7.7,10),(-11.2,7)):
            for z in (3.1,5.3,7.5):
                region = r6.box(.01,length+1,z-.49,z+.49,side*18,yc)
                area = region.cut(cover).Volume()/.01
                assert abs(area-length*.9) < 1e-5
                vents.append({'kind':'side','side':side,'center_y_z_mm':[yc,z],'area_mm2':area})
    step, stl = OUT/'R10_COVER.step', OUT/'R10_COVER.stl'
    geometry = r6.shape_report(cover)
    cq.exporters.export(cover, str(step))
    cq.exporters.export(cover, str(stl), tolerance=.015, angularTolerance=.08)
    restored = cq.importers.importStep(str(step)).val()
    assert restored.isValid() and len(restored.Solids()) == 1
    assert difference(cover, restored) < 1e-4
    mesh = r6.stl_report(stl)
    assert hashes == {str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    report = {'stage':'R10 accepted CAD geometry; see pair GUI check for slicing; physical fit unverified',
              'sliced':False, 'physical_fit_verified':False,
              'parameters':{'side_inset_per_edge_mm':.4,'straight_edge_radius_law':RADIUS_LAW,
                            'corner_arc_external_radius_mm':.6,'internal_cove_radius_mm':INNER_RADIUS,
                            'overall_height_mm':11.4,'mating_band_mm':1.2},
              'geometry':geometry,'mesh':mesh,'mating_band_delta_mm3':rim_delta,
              'base_overlap_mm3':base.intersect(cover).Volume(),'fixed_regions':columns,
              'sensors':sensors,'inner_cove':{'available_new_material_volume_mm3':inner_cove.Volume(),
                 'actual_added_in_old_cavity_mm3':added.intersect(original_cavity).Volume(),
                 'added_outside_intended_cove_mm3':added_outside_cove,
                 'cove_z_extent_mm':[9.5,10.0]},
              'section_checks':sections,'rear_well_edge_mm':wells,
              'thickness_scope':'Selected ordinary-wall sections and four well edges only; not a global minimum-wall guarantee.',
              'vents':vents,'reference_sha256':hashes}
    (OUT/'R10_COVER_check.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()
