"""Prepare a native three-object AirDock60 Bambu project; never slice or print.

Bake each assembly-to-print rotation into its mesh, then put its lowest vertex
on Z=0. MOUNT rotates +120 degrees about world X with its front locating lip
tips down. The backing underside is 1.6 mm above the bed and needs automatic
supports; it does not directly rest on the bed. A 5 mm outer brim remains
configured, but actual brim generation depends on the sliced support footprint.
BAY remains roof down (+180 degrees); TRAY remains bottom down, including its
raised wire-slot lip. The R12 two-material machine/process settings are retained; none of its
meshes, support enforcers, cached previews, statistics or toolpaths are copied.
Fresh slicing and physical support removal remain separate checks.
"""
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
import argparse
import copy
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import math
import uuid
import xml.etree.ElementTree as ET

HERE = Path(__file__).resolve().parent
REFERENCE = HERE.parent/'r12-continuous-round'
TEMPLATE = REFERENCE/'support-interface/R12_PETG_LOCAL_SUPPORT_INTERFACE_BambuStudio.3mf'
spec = importlib.util.spec_from_file_location('airdock60_pack_reference', REFERENCE/'R12_PACK.py')
reference = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reference)
pack, mesh_pack = reference.pack, reference.mesh_pack
CORE, PROD, REL = pack.CORE, pack.PROD, pack.REL
IDENTITY = '1 0 0 0 1 0 0 0 1 0 0 0'
MATRIX = '1 0 0 0 0 1 0 0 0 0 1 0 0 0 0 1'
PARTS = (('MOUNT', 120.0, 120.0), ('BAY', 180.0, 180.0), ('TRAY', 0.0, 240.0))
MOUNT_BRIM = {'brim_type':'outer_only', 'brim_width':'5', 'brim_object_gap':'0.1'}


def uid():
    return str(uuid.uuid4())


def setting(parent, key, value):
    node = parent.find(f"metadata[@key='{key}']")
    if node is None:
        node = ET.SubElement(parent, 'metadata', key=key)
    node.set('value', str(value))


def print_mesh(path, angle):
    vertices, triangles, report = mesh_pack.read_binary_stl(path)
    radians = math.radians(angle)
    cosine, sine = math.cos(radians), math.sin(radians)
    rotated = [(x, cosine*y-sine*z, sine*y+cosine*z) for x,y,z in vertices]
    lift = -min(v[2] for v in rotated)
    vertices = [(x,y,z+lift) for x,y,z in rotated]
    assert abs(min(v[2] for v in vertices)) < 1e-8
    return vertices, triangles, report | {'rotation_world_x_deg':angle, 'baked_z_lift_mm':lift}


def mesh_model(mesh_id, vertices, triangles):
    root = ET.Element(pack.tag('model'), unit='millimeter', requiredextensions='p')
    root.set('{http://www.w3.org/XML/1998/namespace}lang', 'en-US')
    resources = ET.SubElement(root, pack.tag('resources'))
    obj = ET.SubElement(resources, pack.tag('object'), id=str(mesh_id), type='model')
    obj.set(f'{{{PROD}}}UUID', uid())
    mesh = ET.SubElement(obj, pack.tag('mesh'))
    vs, ts = ET.SubElement(mesh, pack.tag('vertices')), ET.SubElement(mesh, pack.tag('triangles'))
    for x,y,z in vertices:
        ET.SubElement(vs, pack.tag('vertex'), x=f'{x:.7f}', y=f'{y:.7f}', z=f'{z:.7f}')
    for a,b,c in triangles:
        ET.SubElement(ts, pack.tag('triangle'), v1=str(a), v2=str(b), v3=str(c))
    return root


def main(input_dir=HERE, output=None, report=None):
    input_dir = Path(input_dir)
    output = Path(output) if output else HERE/'AirDock60_GEOMETRY_BambuStudio.3mf'
    report_path = Path(report) if report else output.with_name('AirDock60_PACK_check.json')
    assert output.suffix.lower() == '.3mf' and output.name.startswith('AirDock60_')
    assert output.resolve() != TEMPLATE.resolve(), 'Never overwrite the reference project'
    assert report_path.name.startswith('AirDock60_') and report_path.suffix == '.json'
    with ZipFile(TEMPLATE) as archive:
        source = {name:archive.read(name) for name in archive.namelist()}
    project = json.loads(source['Metadata/project_settings.config'])
    assert project['printer_model'] == 'Bambu Lab H2D'
    assert project['print_settings_id'] == '0.20mm Standard @BBL H2D'
    assert project['curr_bed_type'] == 'Textured PEI Plate'
    assert project['nozzle_diameter'] == ['0.4','0.4']
    assert project['filament_ids'] == ['GFG99','GFS05']
    assert project['filament_map'] == ['2','1']
    assert project['filament_map_mode'] == 'Manual'
    assert project['filament_is_support'] == ['0','1']
    assert project['support_filament'] == '1' and project['support_interface_filament'] == '2'
    assert project['support_top_z_distance'] == '0' and project['support_interface_spacing'] == '0'
    assert project['enable_prime_tower'] == '1'
    overrides = {'enable_support':'1', 'support_type':'normal(auto)', 'support_style':'snug'}
    project.update(overrides)
    differences = project['different_settings_to_system'][0].split(';')
    project['different_settings_to_system'][0] = ';'.join(dict.fromkeys(differences+list(overrides)))

    model = ET.Element(pack.tag('model'), unit='millimeter', requiredextensions='p')
    model.set('{http://www.w3.org/XML/1998/namespace}lang', 'en-US')
    title = 'AirDock 60 | Split Sensor Dock - flat print geometry'
    for name,value in [('Application','BambuStudio-02.08.02.61'),('BambuStudio:3mfVersion','1'),
                       ('Title',title),('CreationDate',datetime.now(timezone.utc).date().isoformat()),
                       ('Description','Flat MOUNT with automatic snug supports; no toolpaths or physical-fit claim.')]:
        ET.SubElement(model, pack.tag('metadata'), name=name).text = value
    resources = ET.SubElement(model, pack.tag('resources'))
    build = ET.SubElement(model, pack.tag('build'))
    build.set(f'{{{PROD}}}UUID', uid())
    settings = ET.Element('config')
    old_settings = ET.fromstring(source['Metadata/model_settings.config'])
    normal_reference = old_settings.find("object/part[@subtype='normal_part']")
    assert normal_reference is not None
    plate = copy.deepcopy(old_settings.find('plate'))
    # Preserve only native plate metadata; remove cached images and all old instances.
    cache_keys = {'thumbnail_file','thumbnail_no_light_file','top_file','pick_file'}
    for child in list(plate):
        if child.tag != 'metadata' or child.get('key') in cache_keys:
            plate.remove(child)
    for key,value in [('plater_id','1'),('plater_name','AirDock 60 geometry'),('locked','false'),
                      ('filament_map_mode','Manual'),('filament_maps','2 1'),('filament_volume_maps','0 0')]:
        setting(plate,key,value)
    assemble = ET.Element('assemble')
    relationships = ET.Element(f'{{{REL}}}Relationships')
    output_entries = {'[Content_Types].xml':source['[Content_Types].xml']}
    parts, saved_meshes = [], {}

    for index,(name,angle,px) in enumerate(PARTS,1):
        path = input_dir/f'AirDock60_{name}.stl'
        vertices,triangles,mesh_report = print_mesh(path,angle)
        mesh_id,wrapper_id = 2*index-1,2*index
        member = f'3D/Objects/object_{index}.model'
        wrapper = ET.SubElement(resources, pack.tag('object'), id=str(wrapper_id), type='model')
        wrapper.set(f'{{{PROD}}}UUID',uid())
        components = ET.SubElement(wrapper,pack.tag('components'))
        component = ET.SubElement(components,pack.tag('component'),objectid=str(mesh_id),transform=IDENTITY)
        component.set(f'{{{PROD}}}path','/'+member); component.set(f'{{{PROD}}}UUID',uid())
        transform = f'1 0 0 0 1 0 0 0 1 {px:g} 160 0'
        item = ET.SubElement(build,pack.tag('item'),objectid=str(wrapper_id),transform=transform,printable='1')
        item.set(f'{{{PROD}}}UUID',uid())
        obj_cfg = ET.SubElement(settings,'object',id=str(wrapper_id))
        setting(obj_cfg,'name',f'AirDock60_{name}'); setting(obj_cfg,'extruder','1')
        if name == 'MOUNT':
            for key,value in MOUNT_BRIM.items(): setting(obj_cfg,key,value)
        ET.SubElement(obj_cfg,'metadata',face_count=str(len(triangles)))
        part = copy.deepcopy(normal_reference); part.set('id',str(mesh_id)); part.set('uuid',uid())
        for key,value in {'name':f'AirDock60_{name}', 'matrix':MATRIX, 'source_file':path.name,
                          'source_object_id':'0', 'source_volume_id':'0',
                          'source_offset_x':'0', 'source_offset_y':'0', 'source_offset_z':'0'}.items():
            setting(part,key,value)
        stat = part.find('mesh_stat')
        for key in list(stat.attrib):
            stat.set(key,str(len(triangles)) if key=='face_count' else '0')
        obj_cfg.append(part)
        instance = ET.SubElement(plate,'model_instance')
        for key,value in [('object_id',str(wrapper_id)),('instance_id','0'),('identify_id',str(1400+index))]:
            setting(instance,key,value)
        ET.SubElement(assemble,'assemble_item',object_id=str(wrapper_id),instance_id='0',transform=transform,offset='0 0 0')
        ET.SubElement(assemble,'assemble_item',object_id=str(wrapper_id),volume_id='0',transform=IDENTITY)
        ET.SubElement(relationships,f'{{{REL}}}Relationship',Target='/'+member,Id=f'rel-{index}',
                      Type='http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel')
        output_entries[member] = pack.xml(mesh_model(mesh_id,vertices,triangles))
        saved_meshes[member] = (vertices,triangles)
        world_bounds = pack.bounds(vertices,(px,160,0))
        assert 25 <= world_bounds[0][0] < world_bounds[0][1] <= 325
        assert 0 <= world_bounds[1][0] < world_bounds[1][1] <= 320
        assert abs(world_bounds[2][0]) < 1e-6 and world_bounds[2][1] < 320
        parts.append({'part':name, 'stl':path.name, 'stl_sha256':mesh_report['sha256'],
                      'mesh_id':mesh_id, 'wrapper_id':wrapper_id, 'mesh_member':member,
                      'rotation_world_x_deg':angle, 'baked_z_lift_mm':mesh_report['baked_z_lift_mm'],
                      'build_translation_mm':[px,160,0], 'world_bounds_mm':world_bounds,
                      'vertices':len(vertices),'triangles':len(triangles),'closed_manifold':True})
    for left,right in zip(parts,parts[1:]):
        assert right['world_bounds_mm'][0][0]-left['world_bounds_mm'][0][1] >= 10
    settings.extend([plate,assemble])
    root_relationships = ET.Element(f'{{{REL}}}Relationships')
    ET.SubElement(root_relationships,f'{{{REL}}}Relationship',Target='/3D/3dmodel.model',Id='rel-model',
                  Type='http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel')
    output_entries.update({'3D/3dmodel.model':pack.xml(model),'Metadata/model_settings.config':pack.xml(settings),
                           'Metadata/project_settings.config':json.dumps(project,ensure_ascii=False,indent=2).encode(),
                           '3D/_rels/3dmodel.model.rels':pack.xml(relationships),'_rels/.rels':pack.xml(root_relationships)})
    output.parent.mkdir(parents=True,exist_ok=True)
    with ZipFile(output,'w',ZIP_DEFLATED) as archive:
        for name,data in output_entries.items(): archive.writestr(name,data)
    with ZipFile(output) as archive:
        assert archive.testzip() is None
        assert set(archive.namelist()) == set(output_entries)
        assert not any('gcode' in name.lower() or 'support_enforcer' in name.lower() for name in archive.namelist())
        persisted = ET.fromstring(archive.read('3D/3dmodel.model'))
        persisted_settings = ET.fromstring(archive.read('Metadata/model_settings.config'))
        ids = {node.get('id') for node in persisted.find(pack.tag('resources'))}
        assert len(ids) == 3 and ids == {node.get('objectid') for node in persisted.find(pack.tag('build'))}
        assert ids == {node.get('id') for node in persisted_settings.findall('object')}
        assert ids == {node.find("metadata[@key='object_id']").get('value') for node in persisted_settings.find('plate').findall('model_instance')}
        assert len(persisted_settings.findall("object/part[@subtype='normal_part']")) == 3
        assert len(persisted_settings.findall("object/part")) == 3
        for member,(vertices,triangles) in saved_meshes.items():
            loaded_vertices,loaded_triangles = pack.mesh_data(ET.fromstring(archive.read(member)))
            assert loaded_triangles == [tuple(t) for t in triangles]
            assert max(abs(a-b) for p,q in zip(vertices,loaded_vertices) for a,b in zip(p,q)) < 1e-6
    result = {'project':output.name, 'sha256':hashlib.sha256(output.read_bytes()).hexdigest(),
              'source_template':TEMPLATE.relative_to(HERE.parents[2]).as_posix(), 'source_template_sha256':hashlib.sha256(TEMPLATE.read_bytes()).hexdigest(),
              'parts':parts, 'independent_object_count':3, 'old_support_enforcers_copied':False,
              'mount_print_orientation':'World X +120 degrees; front locating lip tips down, backing underside 1.6 mm above bed on automatic supports',
              'mount_backing_underside_above_bed_mm':1.6,
              'mount_object_settings':MOUNT_BRIM,
              'printer':project['printer_settings_id'], 'process':project['print_settings_id'],
              'plate':project['curr_bed_type'], 'material_ids':project['filament_ids'],
              'material_names':project['filament_settings_id'], 'material_map':project['filament_map'],
              'filament_is_support':project['filament_is_support'],
              'nozzle_temperature_c':project['nozzle_temperature'],
              'textured_pei_temperature_c':project['textured_plate_temp'],
              'physical_nozzles':{'right':'PETG body and support skeleton','left':'Support for PLA/PETG interface'},
              'support_type':project['support_type'], 'support_style':project['support_style'],
              'support_filament':project['support_filament'], 'support_interface_filament':project['support_interface_filament'],
              'prime_tower_enabled':True, 'automatic_support_contact_regions_reviewed':False,
              'no_old_cache_or_toolpaths':True, 'sliced':False, 'physical_fit_verified':False,
              'printer_contacted':False, 'print_sent':False,
              'limitations':'Automatic snug supports hold the flat backing above the bed. The 5 mm brim is a requested setting, not a generated-path claim. Fresh slicing/path review and physical adhesion, fit and support removal remain separate checks.'}
    report_path.parent.mkdir(parents=True,exist_ok=True)
    report_path.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--input-dir',type=Path,default=HERE)
    parser.add_argument('--output',type=Path,default=HERE/'AirDock60_GEOMETRY_BambuStudio.3mf')
    parser.add_argument('--report',type=Path)
    args = parser.parse_args()
    main(args.input_dir,args.output,args.report)
