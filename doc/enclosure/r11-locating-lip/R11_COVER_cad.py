"""Six additive locating lips on R10; the original front-shell fit is unverified.

Reported ~1 mm shell-to-board side clearance is an estimate, not measured CAD.
This script changes no reference model, printer state, slicer settings or Git.
"""
from pathlib import Path
import hashlib
import importlib.util
import json
import cadquery as cq

OUT=Path(__file__).resolve().parent
ENCLOSURE=OUT.parent
spec=importlib.util.spec_from_file_location('r10_lip_reference',ENCLOSURE/'r10-rounded-back/R10_COVER_cad.py')
r10=importlib.util.module_from_spec(spec)
spec.loader.exec_module(r10)
r6=r10.r6
LIP_THICKNESS,INSERTION,LEAD_IN=.6,.8,.2
ROOT_TOP,ROOT_SLOPE_TOP,WALL_OVERLAP=.6,.3,.4
SEGMENTS=[
    {'name':'left_upper','axis':'X','side':-1,'range':[6,11]},
    {'name':'left_lower','axis':'X','side':-1,'range':[-11,-6]},
    {'name':'right_upper','axis':'X','side':1,'range':[6,11]},
    {'name':'right_lower','axis':'X','side':1,'range':[-13,-8]},
    {'name':'top_center','axis':'Y','side':1,'range':[-3,3]},
    {'name':'bottom_center','axis':'Y','side':-1,'range':[-3,3]},
]


def lip_segment(item):
    inner=16.9 if item['axis']=='X' else 20.7
    outer=inner+LIP_THICKNESS
    wall_inner=17.4 if item['axis']=='X' else 21.2
    root_outer=wall_inner+WALL_OVERLAP
    assert abs(root_outer-outer-ROOT_SLOPE_TOP)<1e-8
    # One-sided chamfer retains a 0.4 mm toe. The 45-degree shoulder stays
    # at/above Z0, avoiding a root bulge into the unmeasured front shell.
    points=[(inner,-INSERTION),(outer-LEAD_IN,-INSERTION),
            (outer,-INSERTION+LEAD_IN),(outer,0),
            (root_outer,ROOT_SLOPE_TOP),(root_outer,ROOT_TOP),
            (wall_inner,ROOT_TOP),(inner,ROOT_TOP-(wall_inner-inner))]
    points=[(item['side']*radial,z) for radial,z in points]
    a,b=item['range']
    if item['axis']=='X':
        shape=(cq.Workplane('XZ').polyline(points).close().extrude(b-a)
               .translate((0,b,0)).val())
    else:
        shape=(cq.Workplane('YZ').polyline(points).close().extrude(b-a)
               .translate((a,0,0)).val())
    return shape,{'radial_inner_abs_mm':inner,'radial_outer_abs_mm':outer,
                  'root_outer_abs_mm':root_outer,'length_mm':b-a}


def difference(a,b):
    return a.cut(b).Volume()+b.cut(a).Volume()


def main():
    refs=[ENCLOSURE/'r10-rounded-back/R10_COVER.step',
          ENCLOSURE/'r10-rounded-back/R10_COVER.stl',
          ENCLOSURE/'r8-wide-base/R8_BASE.step',ENCLOSURE/'r8-wide-base/R8_BASE.stl']
    hashes={str(p.relative_to(ENCLOSURE)):hashlib.sha256(p.read_bytes()).hexdigest() for p in refs}
    old=cq.importers.importStep(str(refs[0])).val()
    base=cq.importers.importStep(str(refs[2])).val()
    tabs,segments=[],[]
    # Wider than the 12.5 x 6.8 BAT cutout; actual wires are not measured CAD.
    bat_route=r6.box(20,8.8,-1.2,1.0,17.5,-2.8)
    for definition in SEGMENTS:
        tab,measures=lip_segment(definition)
        assert tab.isValid() and len(tab.Solids())==1
        gap,overlap=tab.distance(base),tab.intersect(base).Volume()
        joined=tab.intersect(old).Volume()
        blocked=tab.intersect(bat_route).Volume()
        assert gap>=.19 and overlap<1e-5 and joined>.9 and blocked<1e-5
        tabs.append(tab)
        segments.append({**definition,**measures,'r8_min_distance_mm':gap,
                         'r8_intersection_mm3':overlap,'positive_wall_join_mm3':joined,
                         'bat_route_intersection_mm3':blocked})
    cover=r6.join([old]+tabs)
    assert cover.isValid() and len(cover.Solids())==1
    assert cover.intersect(base).Volume()<1e-5
    removed=old.cut(cover).Volume()
    assert removed<1e-5
    added=cover.cut(old)
    ab=added.BoundingBox()
    assert ab.zmin>=-.800001 and ab.zmax<=.600001
    far=r6.box(100,100,.601,11.6)
    far_delta=difference(cover.intersect(far),old.intersect(far))
    assert far_delta<1e-5
    # Keep the outer 1.3 mm shoulder unchanged. Each lip intentionally covers
    # the innermost 0.1 mm of the former 1.4 mm flat shoulder at its short span.
    shoulder=r6.rounded(37.6,45.2,8,-.81,1.2).cut(
        r6.rounded(35.0,42.6,6.7,-.82,1.21))
    shoulder_delta=difference(cover.intersect(shoulder),old.intersect(shoulder))
    assert shoulder_delta<1e-5
    columns=[]
    for x,y in r6.HOLES:
        fixed=r6.cylinder(3.5,2.2,11.4,x,y)
        delta=difference(cover.intersect(fixed),old.intersect(fixed))
        shaft=cover.intersect(r6.cylinder(1.2,-.9,11.5,x,y)).Volume()
        head=cover.intersect(r6.cylinder(2.4,3.001,11.5,x,y)).Volume()
        assert delta<1e-5 and shaft<1e-5 and head<1e-5
        columns.append({'xy_mm':[x,y],'fixed_region_delta_mm3':delta,
                        'shaft_obstruction_mm3':shaft,'head_obstruction_mm3':head})
    sensors={}
    for name,(x,y,w,h,height) in r6.MODULES.items():
        body=r6.box(w,h,.2,.2+height,x,y)
        overlap=cover.intersect(body).Volume()
        assert overlap<1e-5
        sensors[name]={'overlap_mm3':overlap,'clearance_mm':body.distance(cover),
                       'r10_clearance_mm':body.distance(old)}
    bb=cover.BoundingBox()
    assert abs(bb.zmin+.8)<1e-5 and abs(bb.zmax-11.4)<1e-5
    assert abs(bb.xlen-37.6)<1e-5 and abs(bb.ylen-45.2)<1e-5
    step,stl=OUT/'R11_COVER.step',OUT/'R11_COVER.stl'
    geometry=r6.shape_report(cover)
    cq.exporters.export(cover,str(step))
    cq.exporters.export(cover,str(stl),tolerance=.015,angularTolerance=.08)
    restored=cq.importers.importStep(str(step)).val()
    assert restored.isValid() and len(restored.Solids())==1
    assert difference(restored,cover)<1e-4
    mesh=r6.stl_report(stl)
    assert hashes=={str(p.relative_to(ENCLOSURE)):hashlib.sha256(p.read_bytes()).hexdigest() for p in refs}
    report={'stage':'R11 segmented locating lips; original front-shell fit unverified',
            'physical_fit_verified':False,'sliced':False,
            'front_shell_boundary':'No measured front-shell CAD; reported ~1 mm is an estimate. No front-shell interference or clearance proof.',
            'parameters':{'lip_thickness_mm':LIP_THICKNESS,
                'insertion_below_original_joint_mm':INSERTION,'single_sided_outer_lead_in_mm':LEAD_IN,
                'toe_thickness_mm':.4,'shoulder_top_z_mm':ROOT_TOP,
                'root_transition':'Visible inner 45-degree shoulder from Z0.1 to Z0.6; outer wall lap stays at/above Z0',
                'radial_wall_overlap_mm':WALL_OVERLAP,'minimum_required_R8_clearance_mm':.19,
                'original_joint_z_mm':0,'original_cover_back_z_mm':11.4,
                'cover_foot_contact_z_mm':2.2,'protected_outer_shoulder_straight_width_mm':1.3},
            'geometry':geometry,'mesh':mesh,'segments':segments,
            'all_R10_material_preserved_removed_mm3':removed,
            'r8_body_intersection_mm3':cover.intersect(base).Volume(),
            'new_lips_to_R8_min_clearance_mm':min(v['r8_min_distance_mm'] for v in segments),
            'new_material':{'volume_mm3':added.Volume(),'z_min_max_mm':[ab.zmin,ab.zmax],
                            'far_from_joint_delta_mm3':far_delta},
            'protected_outer_mating_shoulder_delta_mm3':shoulder_delta,
            'screw_regions':columns,'sensors':sensors,'reference_sha256':hashes,
            'printing_note':'Assembly Z=-0.8..11.4. Rotate 180 degrees around X and rest the exterior back on the bed. Print height 12.2 mm; original joint Z0 is not the lip tip.'}
    (OUT/'R11_COVER_check.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
