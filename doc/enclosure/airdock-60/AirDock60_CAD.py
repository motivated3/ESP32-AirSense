"""AirDock60 three-part 60-degree fit prototype. No printer communication.

World axes: X across the front view, Y rearward, Z upward from the base.
Old shell axes remain in AirDock60_MOUNT.py; its rigid transform preserves up/BAT.
"""
from pathlib import Path
import importlib.util, json, math, hashlib, struct
import cadquery as cq

OUT=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('airdock60_mount',OUT/'AirDock60_MOUNT.py')
mount=importlib.util.module_from_spec(spec); spec.loader.exec_module(mount)
REAR, WIDTH, HEIGHT=39.0,37.6,14.0
WALL, GAP, FIT=1.4,.25,.25
DOCK_SHOULDER=4.15  # q=3.4 backing + 1 mm air gap - .25 mm dock clearance.
LOCK_X,LOCK_Y=6.5,14.3
MODULES={'SCD41':(-16.0,-2.6,13.4,35.0,1.7,10.7),
         'SFA40':(-.6,16.4,20.0,35.0,1.7,10.7)}
ROOF_VENT_X=(-14,-11,-8,-5,-2,2,5,8,11,14)
ROOF_VENT_Y,ROOF_VENT_LENGTH,ROOF_VENT_WIDTH=27.5,12.0,1.4

def box(w,d,z0,z1,x=0,y=0):
    return cq.Workplane('XY').box(w,d,z1-z0,centered=(True,True,False)).translate((x,y,z0)).val()

def cylinder(radius,z0,z1,x=0,y=0):
    return cq.Workplane('XY').center(x,y).circle(radius).extrude(z1-z0).translate((0,0,z0)).val()

def rounded(w,d,r,z0,z1,x=0,y=0):
    return cq.Workplane(obj=box(w,d,z0,z1,x,y)).edges('|Z').fillet(r).val()

def join(items):
    result=items[0]
    for s in items[1:]: result=result.fuse(s)
    return result.clean()

def old_box(w,h,z0,z1,x=0,y=0):
    return box(w,h,z0,z1,x,y)

def local_rear_halfspace(z0):
    return mount.to_world(old_box(160,180,z0,100))

def hex_prism(af,z0,z1,x,y):
    radius=af/math.sqrt(3)
    pts=[(x+radius*math.cos(math.pi/6+i*math.pi/3),
          y+radius*math.sin(math.pi/6+i*math.pi/3)) for i in range(6)]
    return cq.Workplane('XY').polyline(pts).close().extrude(z1-z0).translate((0,0,z0)).val()

def sensor_envelopes():
    return {name:box(x1-x0,y1-y0,z0,z1,(x0+x1)/2,(y0+y1)/2)
            for name,(x0,x1,y0,y1,z0,z1) in MODULES.items()}

def wire_passage():
    # Bottom-open U: existing soldered wires are laid in from below. Closing
    # the tray supplies the floor; no individual printed part has a wire bore.
    tool=box(3.6,21,-5,9.5,0,5.5)
    return cq.Workplane(obj=tool).edges('|Y').edges('>Z').fillet(.3).val()

def build_mount():
    base_local=mount.build_mount_local()
    ribs=[]
    # The new dock connects to both side frames, above the frozen low interface.
    for side in (-1,1):
        ribs.append(mount.to_world(old_box(6.2,7,2.95,DOCK_SHOULDER,side*15.3,-13)))
    ribs.append(mount.to_world(old_box(30,3,2.95,DOCK_SHOULDER,0,-10)))
    # Extend only the roots towards the plate; the guide ends, nut and bolt
    # stay in their original world positions. A shortened shoulder alone
    # would leave the guides attached by almost a point.
    keys=[box(4.6,5.35,6,9.4,side*12.5,9.525) for side in (-1,1)]
    lock=box(6.2,10.15,6.8,11,LOCK_X,11.925)
    lock=lock.intersect(local_rear_halfspace(2.95))
    result=join([mount.to_world(base_local),*ribs,*keys,lock])
    # Nut drops/slides in from the rear, while side flats prevent rotation.
    nut=hex_prism(4.3,8,9.8,LOCK_X,LOCK_Y)
    entry=box(4.4,3.4,8,9.8,LOCK_X,16.0)
    result=result.cut(nut).cut(entry)
    result=result.cut(cylinder(1.2,6.7,11.1,LOCK_X,LOCK_Y))
    # Do not let new ribs/keys obstruct old screw heads or their straight tool path.
    for x in (-12,12):
        for y in (-18,18):
            head=cylinder(2.4,mount.HEAD_SEAT,60,x,y)
            result=result.cut(mount.to_world(head))
    # Four soft wires; front/mount side is deliberately a narrow passage.
    result=result.cut(wire_passage())
    return result.clean(),base_local

def bay_outline():
    outer=rounded(WIDTH,REAR,4,0,HEIGHT,y=REAR/2)
    outer=cq.Workplane(obj=outer).edges('>Z').fillet(2).edges('<Z').fillet(.6).val()
    return outer.intersect(local_rear_halfspace(DOCK_SHOULDER+GAP))

def build_bay():
    outer=bay_outline()
    cavity=rounded(34.8,25.3,2.0,1.4,12.6,y=24.95)
    cavity=cq.Workplane(obj=cavity).edges('>Z').fillet(.2).val()
    full=outer.cut(cavity)
    # Two banks on the roof directly over the sensor cavity. Roof-down print
    # orientation makes these through-Z holes, without extra bridge supports.
    for x in ROOF_VENT_X:
        vent=(cq.Workplane('XY').center(x,ROOF_VENT_Y)
              .slot2D(ROOF_VENT_LENGTH,ROOF_VENT_WIDTH,90).extrude(1.6)
              .translate((0,0,12.5)).val())
        full=full.cut(vent)
    # Side openings only; rear apertures are restricted to the rear wall.
    for y in (20,23.3,26.6,29.9,33.2):
        pts=[(y-.65,5.8),(y+.65,5.8),(y+.65,10.15),(y,10.8),(y-.65,10.15)]
        full=full.cut(cq.Workplane('YZ').polyline(pts).close().extrude(45,both=True).val())
    for x in (-12.5,-9,-5.5,-2,2,5.5,9,12.5):
        pts=[(x-.6,5.8),(x+.6,5.8),(x+.6,10.2),(x,10.8),(x-.6,10.2)]
        cut=cq.Workplane('XZ').polyline(pts).close().extrude(45,both=True).val()
        full=full.cut(cut.intersect(box(75,3,0,16,y=REAR-.5)))
    full=full.cut(box(100,100,-1,1.4,y=20))
    additions=[]
    for side in (-1,1):
        additions.append(box(6.2,5,4.8,10.8,side*12.5,10.5))
        additions.append(box(6.2,2,4.8,10.8,side*15.6,11.8))
    # Compression column transfers the bolt load without bending the thin tray.
    additions.extend([box(6.4,6,3,6.8,LOCK_X,LOCK_Y),
                      box(12.4,2,3,6.8,12.2,LOCK_Y)])
    # Installed bay prevents the loose nut from sliding out of the rear entry.
    additions.extend([box(6.8,.8,7.8,10.2,LOCK_X,18.2),
                      box(12.4,1.2,7.8,10.2,12.2,18.2)])
    # Rear hooks rest on a 1 mm ledge. Side pillars support the ledge; an open
    # underside rear window lets hooks slide +Y clear before the tray drops.
    for x in (-8,8):
        additions.append(box(7.8,2.0,1.4,5.0,x,REAR-1.0))
    result=join([full,*additions]).intersect(outer)
    # Through-open front slots: fixed keys exit toward -Y during assembly.
    for side in (-1,1):
        result=result.cut(box(5.1,70,5.75,9.65,side*12.5,12.45-35))
    # The fixed lock tab slides out above the compression column.
    result=result.cut(box(6.7,70,6.8,11.25,LOCK_X,17.25-35))
    result=result.cut(cylinder(1.2,2.9,7,LOCK_X,LOCK_Y))
    result=result.cut(cylinder(3.85,1.39,3.0,LOCK_X,LOCK_Y))
    for x in (-8,8):
        result=result.cut(box(5.4,3.5,2.4,3.85,x,REAR-.95))
        result=result.cut(box(5.4,2,1.39,3.85,x,REAR-.4))
    result=result.cut(wire_passage())
    return result.clean(),cavity

def build_tray():
    # Bottom face is flat; a small peripheral relief avoids a forced press fit.
    outline=rounded(WIDTH-.4,REAR-.4,3.8,0,1.4,y=REAR/2)
    result=outline.intersect(local_rear_halfspace(DOCK_SHOULDER+GAP+.05))
    boss=cylinder(3.6,1.35,3,LOCK_X,LOCK_Y)
    rails=[]
    for x0,x1,y0,y1,z0,z1 in MODULES.values():
        x,y=(x0+x1)/2,(y0+y1)/2; w,d=x1-x0,y1-y0
        outside=rounded(w+1.6,d+1.6,1.2,1.35,2.6,x,y)
        inside=box(w+.5,d+.5,1.2,2.8,x,y)
        rim=outside.cut(inside)
        # Solder end is open; wires pass between the low side rails.
        rim=rim.cut(box(w-.8,2,1.3,2.8,x,y0-.5))
        rails.append(rim)
    tongues=[]
    for x in (-8,8):
        tongues.extend([box(5,2.0,2.6,3.6,x,REAR-1.2),
                        box(5,.5,1.35,3.6,x,REAR-.45)])
    lip=rounded(3.1,21,.3,1.35,7.5,0,5.5)
    lip=cq.Workplane(obj=lip).edges('>Z').fillet(.3).val()
    lip=lip.intersect(local_rear_halfspace(DOCK_SHOULDER+GAP+.10))
    result=join([result,boss,*rails,*tongues,lip])
    result=result.cut(cylinder(1.2,-.1,3.1,LOCK_X,LOCK_Y))
    result=result.cut(cylinder(2.2,-.1,1.8,LOCK_X,LOCK_Y))
    return result.clean()

def screw_and_nut():
    head=cylinder(2,.2,1.8,LOCK_X,LOCK_Y)
    shaft=cylinder(1,1.8,9.8,LOCK_X,LOCK_Y)
    nut=hex_prism(4,8,9.6,LOCK_X,LOCK_Y).cut(cylinder(1,7.9,9.7,LOCK_X,LOCK_Y))
    return join([head,shaft]),nut

def build_parts():
    adapter,local=build_mount(); bay,cavity=build_bay(); tray=build_tray()
    return {'mount':adapter,'bay':bay,'tray':tray},local,cavity

def report_shape(s):
    b=s.BoundingBox()
    return {'valid':s.isValid(),'solids':len(s.Solids()),'volume_mm3':round(s.Volume(),4),
            'bbox_mm':[round(b.xlen,4),round(b.ylen,4),round(b.zlen,4)]}

def remove_zero_area_stl(path):
    """Discard only exactly collapsed binary facets from OCC tessellation.

    Such a facet contributes no surface or volume. All retained coordinates
    remain byte-identical; the packer's independent manifold test still applies.
    """
    raw=path.read_bytes(); count=struct.unpack_from('<I',raw,80)[0]
    assert len(raw)==84+50*count
    kept=[]
    for i in range(count):
        row=raw[84+50*i:134+50*i]
        values=struct.unpack('<12fH',row)
        points=[tuple(values[j:j+3]) for j in (3,6,9)]
        if len(set(points))==3:kept.append(row)
    if len(kept)!=count:
        path.write_bytes(raw[:80]+struct.pack('<I',len(kept))+b''.join(kept))
    return count-len(kept)

def main():
    parts,local,cavity=build_parts()
    report={'parts':{n:report_shape(s) for n,s in parts.items()},
            'mount_interface':mount.verify_mount_local(local),
            'roof_grille':{'count':len(ROOF_VENT_X),
                'slot_length_width_mm':[ROOF_VENT_LENGTH,ROOF_VENT_WIDTH],
                'centers_x_mm':list(ROOF_VENT_X),'center_y_mm':ROOF_VENT_Y,
                'rib_width_mm':1.6,'central_rib_width_mm':2.6,
                'open_area_mm2':len(ROOF_VENT_X)*((ROOF_VENT_LENGTH-ROOF_VENT_WIDTH)*ROOF_VENT_WIDTH+math.pi*(ROOF_VENT_WIDTH/2)**2),
                'scope':'Roof vents retained. Backing and front dock updated for 1 mm gap. Airflow and temperature reduction unverified.'},
            'backing_revision':{'plate_thickness_mm':mount.THICKNESS,
                'original_screw_seat_q_mm':mount.HEAD_SEAT,
                'normal_bay_gap_mm':DOCK_SHOULDER+GAP-mount.BACK,
                'backing_vents':{'count':len(mount.VENT_X),'length_width_mm':[mount.VENT_LENGTH,mount.VENT_WIDTH]},
                'front_mating_rim':True,'rim_projection_mm':mount.RIM_DEPTH,
                'red_edge_total_thickness_mm':mount.THICKNESS+mount.RIM_DEPTH,
                'locating_tab_count':len(mount.LIP_SEGMENTS)},
            'physical_fit_verified':False,'sliced':False,'print_sent':False}
    for name,shape in parts.items():
        assert shape.isValid() and len(shape.Solids())==1,(name,report['parts'][name])
        cq.exporters.export(shape,str(OUT/f'AirDock60_{name.upper()}.step'))
        mesh=OUT/f'AirDock60_{name.upper()}.stl'
        cq.exporters.export(shape,str(mesh),tolerance=.02,angularTolerance=.08)
        report['parts'][name]['zero_area_export_facets_removed']=remove_zero_area_stl(mesh)
    (OUT/'AirDock60_BUILD_check.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(report,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
