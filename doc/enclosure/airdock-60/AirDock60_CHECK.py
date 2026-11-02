"""Independent checks of exported STEP parts and assembly motion envelopes."""
from pathlib import Path
import importlib.util,json,math
import cadquery as cq

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('airdock60_geometry',HERE/'AirDock60_CAD.py')
g=importlib.util.module_from_spec(spec); spec.loader.exec_module(g)

def volume(a,b):
    return a.copy().intersect(b.copy()).Volume()

def main():
    parts={n:cq.importers.importStep(str(HERE/f'AirDock60_{n.upper()}.step')).val()
           for n in ('mount','bay','tray')}
    assert all(s.isValid() and len(s.Solids())==1 for s in parts.values())
    checks={'parts':{n:g.report_shape(s) for n,s in parts.items()},'intersections':{},'modules':{}}
    # Check the requested plate on the exported solid, not only source constants.
    plate=g.mount.to_world(g.box(2,2,2.2,3.4,x=15,y=4))
    missing=plate.copy().cut(parts['mount'].copy()).Volume()
    assert missing<1e-4,('1.2 mm backing plate missing material',missing)
    # Eight rounded upper vents must pass through the full backing thickness.
    backing_vents=[]
    for x in (-10.5,-7.5,-4.5,-1.5,1.5,4.5,7.5,10.5):
        slot=(cq.Workplane('XY').center(x,7).slot2D(14,1.4,90)
              .extrude(1.4).translate((0,0,2.1)).val())
        blocked=volume(parts['mount'],g.mount.to_world(slot))
        assert blocked<1e-4,('backing vent blocked',x,blocked)
        backing_vents.append({'local_x_mm':x,'blocked_mm3':blocked})
    checks['backing_vents']=backing_vents
    # Side skins start 1 mm behind the new q=3.4 backing face. Probe small
    # lands away from the guide openings and outer XY/Z roundovers.
    seam=[]
    for x in (-18,18):
        for z in (7,11):
            # Normal-direction probes avoid assumptions about the Z lean.
            band=g.box(.2,50,z,z+.2,x,15).intersect(g.local_rear_halfspace(4.4))
            band=band.cut(g.local_rear_halfspace(4.45))
            present=volume(parts['bay'],band)
            assert present>.0001,('bay side skin does not reach 1mm seam',x,z,present)
            seam.append({'world_xz_mm':[x,z],'front_skin_probe_mm3':present})
    too_far=volume(parts['bay'],g.local_rear_halfspace(-20).cut(g.local_rear_halfspace(4.399)))
    assert too_far<1e-4,('bay crosses 1mm gap',too_far)
    checks['backing_and_gap']={'plate_thickness_mm':1.2,'screw_seat_q_mm':3.0,
        'normal_gap_mm':1.0,'horizontal_gap_mm':1/math.cos(math.radians(30)),
        'front_skin_probes':seam,'bay_material_in_gap_mm3':too_far}
    # The user's red dimension is 1.2 mm plate + 0.8 mm rim = 2.0 mm,
    # not the old reference joint-to-ear height of 2.2 mm.
    front=g.mount.to_world(g.box(60,70,-5,1.399))
    # Six locating lips may extend another 0.8 mm from the rim. Exclude
    # their exact solids so the check measures the continuous perimeter.
    for definition in g.mount.LIP_SEGMENTS:
        tab=g.mount.to_world(g.mount.lip.lip_segment(definition)[0].translate((0,0,1.4)))
        front=front.cut(tab)
    excess=volume(parts['mount'],front)
    assert excess<1e-4,('perimeter projects beyond requested 0.8 mm',excess)
    rim_probes=[]
    for x,y in ((18,0),(-18,0),(0,21.8),(5,-21.8)):
        probe=g.mount.to_world(g.box(.15,.15,1.4,2.2,x,y))
        missing=probe.copy().cut(parts['mount'].copy()).Volume()
        assert missing<1e-4,('perimeter rim missing',x,y,missing)
        rim_probes.append({'local_xy_mm':[x,y],'missing_mm3':missing})
    lips=[]
    for definition in g.mount.LIP_SEGMENTS:
        shape=g.mount.to_world(g.mount.lip.lip_segment(definition)[0].translate((0,0,1.4)))
        missing=shape.copy().cut(parts['mount'].copy()).Volume()
        assert missing<1e-4,('locating tab missing',definition,missing)
        lips.append({'definition':definition,'missing_mm3':missing})
    assert len(lips)==6
    checks['front_mating_rim']={'shoulder_q_mm':1.4,'rim_under_plate_mm':.8,
        'red_edge_total_thickness_mm':2.0,'excess_rim_material_mm3':excess,
        'lip_insertion_mm':.8,'rim_probes':rim_probes,'locating_tabs':lips,
        'front_shell_physical_fit_verified':False}
    # The former enclosure wall/lip is intentionally removed. Above the lower
    # stand, backing material must never extend behind the flat q=3.4 plane.
    upper=g.box(150,150,14.01,100,y=20)
    rear=g.local_rear_halfspace(3.401)
    extra=parts['mount'].copy().intersect(upper).intersect(rear).Volume()
    checks['extra_backing_above_stand_mm3']=extra
    assert extra<1e-4,extra
    seats=[]
    for x in (-12,12):
        for y in (-18,18):
            land=g.cylinder(2.35,2.2,3.0,x,y).cut(g.cylinder(1.21,2.19,3.01,x,y))
            land=g.mount.to_world(land)
            missing=land.copy().cut(parts['mount'].copy()).Volume()
            seats.append({'old_xy':[x,y],'missing_bearing_mm3':missing})
            assert missing<1e-4,(x,y,missing)
    checks['original_screw_bearing_lands']=seats
    # Independently probe the actual exported roof slots through to the cavity.
    grilles=[]
    for x in (-14,-11,-8,-5,-2,2,5,8,11,14):
        slot=(cq.Workplane('XY').center(x,27.5).slot2D(12,1.4,90)
              .extrude(3.3).translate((0,0,10.8)).val())
        blocked={n:volume(part,slot) for n,part in parts.items()}
        grilles.append({'world_xy_mm':[x,27.5],'blocked_mm3':blocked})
        assert max(blocked.values())<1e-4,(x,blocked)
    checks['sensor_bay_roof_grilles']=grilles
    checks['grille_limitation']='Through-open to the sensor cavity; airflow and thermal improvement require measurement.'
    for a,b in [('mount','bay'),('mount','tray'),('bay','tray')]:
        v=volume(parts[a],parts[b]); checks['intersections'][f'{a}_{b}_mm3']=v
        assert v<1e-4,(a,b,v)
    for name,sensor in g.sensor_envelopes().items():
        rows={n:volume(part,sensor) for n,part in parts.items()}
        checks['modules'][name]=rows
        assert max(rows.values())<1e-4,(name,rows)
    screw,nut=g.screw_and_nut()
    for n,part in parts.items():
        for label,hardware in [('M2x8',screw),('M2nut',nut)]:
            v=volume(part,hardware);checks['intersections'][f'{n}_{label}_mm3']=v
            assert v<1e-4,(n,label,v)
    # Check the real reused base, not just four idealized standoffs.
    original_base=cq.importers.importStep(str(HERE.parent/'r8-wide-base/R8_BASE.step')).val()
    original_base=g.mount.to_world(original_base)
    rows={n:volume(s,original_base) for n,s in parts.items()}
    checks['reused_R8']=rows
    assert max(rows.values())<1e-4,rows
    # The user removes the whole bay before using any original screw.
    tools=[]
    for x in (-12,12):
        for y in (-18,18):
            tool=g.mount.to_world(g.cylinder(2,3.01,60,x,y))
            v=volume(parts['mount'],tool)
            tools.append({'old_xy':[x,y],'tool_diameter_mm':4,'blocked_mm3':v})
            assert v<1e-4,(x,y,v)
    checks['original_screw_tool_paths']=tools
    # Assembled cable channel: 1.6 mm bundle above the split tray lip.
    probe=cq.Solid.makeCylinder(.8,9,cq.Vector(0,6.9,8.5),cq.Vector(0,1,0))
    rows={n:volume(part,probe) for n,part in parts.items()}
    checks['split_wire_channel_1p6mm_probe']=rows
    assert max(rows.values())<1e-4,rows
    drop_in=[]
    for z in (-3,-1,0,1,2,3,4,5,6,7,8.5):
        cable=cq.Solid.makeCylinder(.8,9,cq.Vector(0,6.9,z),cq.Vector(0,1,0))
        rows={n:volume(parts[n],cable) for n in ('mount','bay')}
        drop_in.append({'bundle_center_world_z_mm':z,'blocked_mm3':rows})
        assert max(rows.values())<1e-4,(z,rows)
    checks['pre_soldered_wire_bottom_entry_before_tray']=drop_in
    # The assembled removable bay and sensors slide +Y before tray disassembly.
    motion=[]
    sensors=g.sensor_envelopes()
    for dy in (0,.1,.25,.5,1,2,4,8):
        rows={n:volume(parts['mount'],s.translate((0,dy,0)))
              for n,s in {'bay':parts['bay'],'tray':parts['tray'],**sensors}.items()}
        motion.append({'rearward_mm':dy,'intersections_mm3':rows})
        assert max(rows.values())<1e-4,(dy,rows)
    checks['whole_bay_removal']=motion
    # After removing the whole bay, unload the ledges by 0.1 mm, slide the
    # tray 1.0 mm rearward and lower it. Modules never sweep toward front keys.
    motion=[]
    route=[(0,0),(0,-.1)]+[(i/10,-.1) for i in range(1,11)]
    route += [(1.0,-v) for v in (.2,.5,1,2,4,8,12,16)]
    for dy,dz in route:
        rows={}
        for n,s in {'tray':parts['tray'],**sensors}.items():
            moved=s.translate((0,dy,dz))
            rows[n]=volume(parts['bay'],moved)
            rows[n+'_mount']=volume(parts['mount'],moved)
        motion.append({'rearward_mm':dy,'down_mm':-dz,'intersections_mm3':rows})
        assert max(rows.values())<1e-4,(dy,dz,rows)
    checks['tray_removal_with_bay_and_mount_held']=motion
    nut_motion=[]
    for dy in (0,.1,.25,.5,1,2,3,4,5,6,8):
        v=volume(parts['mount'],nut.translate((0,dy,0)))
        nut_motion.append({'rearward_mm':dy,'blocked_by_mount_mm3':v})
        assert v<1e-4,(dy,v)
    checks['nut_insertion_before_bay_installed']=nut_motion
    retained=volume(parts['bay'],nut.translate((0,3,0)))
    checks['installed_bay_nut_escape_blocked_mm3']=retained
    assert retained>0,'Installed bay must prevent the loose nut escaping rearward'
    checks.update(physical_fit_verified=False,mechanical_strength_verified=False,
                  thermal_performance_verified=False,
                  note='Sampled assembly sweeps and ideal hardware envelopes, not a physical fit or continuous swept-solid proof.')
    target=HERE/'AirDock60_ASSEMBLY_check.json'
    target.write_text(json.dumps(checks,ensure_ascii=False,indent=2)+'\n')
    print(target); print('PASS: exported solids, interfaces, modules, hardware and sampled removal paths')

if __name__=='__main__':main()
