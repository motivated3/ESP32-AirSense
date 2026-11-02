"""Publish the guarded flat-print AUTO project; never slice or print.

No manual contact enforcers are retained. Normal meshes, material settings and
print poses stay identical to the validated AirDock60_GEOMETRY baseline.
"""
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
import argparse
import hashlib
import importlib.util
import json
import xml.etree.ElementTree as ET

HERE = Path(__file__).resolve().parent
SOURCE = HERE/'AirDock60_GEOMETRY_BambuStudio.3mf'
SOURCE_SHA = '3c8cff7f480a51549ad9a606ff2da6e4c8af4f2daf68f0b9d726f177682668d1'
STEP_SHA = {
    'MOUNT':'1b5f5bbca4f5750d32abf4aae76b25f1f0fe38029340db74eb7c7c71e1b45294',
    'BAY':'a4adcd49d3dd5d326fffc454d3e3836fd65539b3f265535d4707f207d7d5100e',
    'TRAY':'7c1bfe6dfb45beb9bf9af3154c1632cb931680ca6f58065a07c18346c424d88d',
}
POSES = (('MOUNT',120.,120.), ('BAY',180.,180.), ('TRAY',0.,240.))
spec = importlib.util.spec_from_file_location('airdock60_flat_reference', HERE/'AirDock60_PACK.py')
ref = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ref)
tag, xml = ref.pack.tag, ref.pack.xml


def sha(data):
    return hashlib.sha256(data).hexdigest()


def validate(entries, baseline):
    """Recheck current source meshes and their actual persisted print poses."""
    members = {f'3D/Objects/object_{i}.model' for i in range(1,4)}
    assert set(entries) == members | {'[Content_Types].xml','3D/3dmodel.model',
        'Metadata/model_settings.config','Metadata/project_settings.config',
        '3D/_rels/3dmodel.model.rels','_rels/.rels'}
    project = json.loads(entries['Metadata/project_settings.config'])
    expected = {'printer_model':'Bambu Lab H2D', 'print_settings_id':'0.20mm Standard @BBL H2D',
        'curr_bed_type':'Textured PEI Plate', 'nozzle_diameter':['0.4','0.4'],
        'filament_ids':['GFG99','GFS05'], 'filament_map':['2','1'],
        'filament_map_mode':'Manual', 'filament_is_support':['0','1'],
        # Native H2D preset retains unused temperature slots; active material
        # deposition targets are checked again in the fresh sliced G-code.
        'nozzle_temperature':['255','255','255','220','210','210'], 'enable_support':'1',
        'support_type':'normal(auto)', 'support_style':'snug',
        'support_filament':'1', 'support_interface_filament':'2',
        'support_interface_top_layers':'3', 'support_top_z_distance':'0',
        'support_interface_spacing':'0', 'support_on_build_plate_only':'0',
        'support_threshold_angle':'30', 'enable_prime_tower':'1'}
    for key,value in expected.items():
        assert project[key] == value, (key,project[key],value)
    model = ET.fromstring(entries['3D/3dmodel.model'])
    settings = ET.fromstring(entries['Metadata/model_settings.config'])
    resources, build = model.find(tag('resources')), model.find(tag('build'))
    plate = settings.find('plate')
    assert len(resources) == len(build) == len(settings.findall('object')) == 3
    assert len(plate.findall('model_instance')) == 3
    assert len(settings.findall('object/part')) == 3
    assert len(settings.findall("object/part[@subtype='normal_part']")) == 3
    assert not settings.findall("object/part[@subtype='support_enforcer']")
    assert len(baseline['parts']) == 3
    verified = []
    for index,((name,angle,px),part) in enumerate(zip(POSES,baseline['parts']),1):
        assert part['part'] == name and part['rotation_world_x_deg'] == angle
        assert sha((HERE/f'AirDock60_{name}.step').read_bytes()) == STEP_SHA[name], f'Review changed STEP: {name}'
        assert part['stl'] == f'AirDock60_{name}.stl'
        # print_mesh independently checks the current STL's closed edge pairs.
        vertices,triangles,mesh_report = ref.print_mesh(HERE/part['stl'],angle)
        assert mesh_report['sha256'] == part['stl_sha256']
        assert abs(mesh_report['baked_z_lift_mm']-part['baked_z_lift_mm']) < 1e-8
        assert part['mesh_id'] == 2*index-1 and part['wrapper_id'] == 2*index
        member = f'3D/Objects/object_{index}.model'
        assert part['mesh_member'] == member
        loaded_vertices,loaded_triangles = ref.pack.mesh_data(ET.fromstring(entries[member]))
        assert loaded_triangles == [tuple(t) for t in triangles]
        assert len(loaded_vertices) == len(vertices)
        assert max(abs(a-b) for p,q in zip(vertices,loaded_vertices) for a,b in zip(p,q)) < 1e-6
        wrapper_id,mesh_id = str(part['wrapper_id']),str(part['mesh_id'])
        wrapper = resources.find(f"{tag('object')}[@id='{wrapper_id}']")
        components = wrapper.find(tag('components'))
        assert len(components) == 1
        assert components[0].get('objectid') == mesh_id
        assert components[0].get(f'{{{ref.PROD}}}path') == '/'+member
        assert components[0].get('transform') == ref.IDENTITY
        translation = [px,160,0]
        assert part['build_translation_mm'] == translation
        item = build.find(f"{tag('item')}[@objectid='{wrapper_id}']")
        assert list(map(float,item.get('transform').split())) == [1,0,0,0,1,0,0,0,1,*translation]
        assert item.get('printable') == '1'
        cfg = settings.find(f"object[@id='{wrapper_id}']")
        assert cfg.find("metadata[@key='extruder']").get('value') == '1'
        assert cfg.find("part[@subtype='normal_part']").get('id') == mesh_id
        assert cfg.find('part/metadata[@key="matrix"]').get('value') == ref.MATRIX
        instances = [v for v in plate.findall('model_instance')
            if v.find("metadata[@key='object_id']").get('value') == wrapper_id]
        assert len(instances) == 1
        actual_bounds = ref.pack.bounds(loaded_vertices,translation)
        assert max(abs(a-b) for p,q in zip(actual_bounds,part['world_bounds_mm']) for a,b in zip(p,q)) < 1e-6
        assert abs(actual_bounds[2][0]) < 1e-6
        if name == 'MOUNT':
            assert all(cfg.find(f"metadata[@key='{key}']").get('value') == value
                for key,value in ref.MOUNT_BRIM.items())
        verified.append({'part':name,'rotation_world_x_deg':angle,'world_bounds_mm':actual_bounds,
            'stl_sha256':mesh_report['sha256'],'closed_manifold':True,
            'current_STL_matches_print_mesh':True})
    return model,settings,project,verified


def main(source=SOURCE, output=HERE/'AirDock60_BambuStudio.3mf', report=None):
    source,output = Path(source),Path(output)
    report_path = Path(report) if report else HERE/'AirDock60_SUPPORT_check.json'
    assert source.resolve() != output.resolve()
    assert output.name.startswith('AirDock60_') and output.suffix == '.3mf'
    assert report_path.name.startswith('AirDock60_') and report_path.suffix == '.json'
    assert sha(source.read_bytes()) == SOURCE_SHA, 'Review the changed baseline before publishing'
    baseline = json.loads((HERE/'AirDock60_PACK_check.json').read_text())
    assert baseline['sha256'] == SOURCE_SHA
    with ZipFile(source) as archive:
        assert archive.testzip() is None
        entries = {n:archive.read(n) for n in archive.namelist()}
    model,settings,project,verified = validate(entries,baseline)
    originals = dict(entries)
    for md in model.findall(tag('metadata')):
        if md.get('name') == 'Title': md.text = 'AirDock 60 | 分舱底座版 | 平放打印'
    ref.setting(settings.find('plate'),'plater_name','AirDock 60 平放打印')
    entries.update({'3D/3dmodel.model':xml(model),'Metadata/model_settings.config':xml(settings)})
    output.parent.mkdir(parents=True,exist_ok=True)
    with ZipFile(output,'w',ZIP_DEFLATED) as archive:
        for name,data in entries.items(): archive.writestr(name,data)
    with ZipFile(output) as archive:
        assert archive.testzip() is None and set(archive.namelist()) == set(entries)
        assert all(archive.read(n) == data for n,data in originals.items()
            if n not in ('3D/3dmodel.model','Metadata/model_settings.config'))
        loaded_cfg = ET.fromstring(archive.read('Metadata/model_settings.config'))
        assert len(loaded_cfg.findall('object/part')) == 3
        assert len(loaded_cfg.findall("object/part[@subtype='normal_part']")) == 3
    normal_meshes = {n:sha(data) for n,data in entries.items() if n.startswith('3D/Objects/')}
    result = {'source':source.name,'source_sha256':SOURCE_SHA,'output':output.name,
        'output_sha256':sha(output.read_bytes()),'source_step_sha256':STEP_SHA,
        'publication_mode':'Flat geometry baseline with automatic snug supports',
        'normal_mesh_members_byte_identical':normal_meshes,'normal_part_count':3,
        'nonprinting_enforcer_count':0,'enforcers_by_part':{name:0 for name in STEP_SHA},
        'verified_print_poses':verified,'mount_print_orientation':baseline['mount_print_orientation'],
        'mount_backing_underside_above_bed_mm':1.6,'mount_object_settings':ref.MOUNT_BRIM,
        'project_settings_byte_identical_to_baseline':True,'support_type':project['support_type'],
        'support_style':project['support_style'],'material_ids':project['filament_ids'],
        'material_map':project['filament_map'],'support_filament':project['support_filament'],
        'support_interface_filament':project['support_interface_filament'],
        'support_interface_top_layers':project['support_interface_top_layers'],
        'no_cached_slice_or_toolpaths':True,'sliced':False,'printer_contacted':False,'print_sent':False,
        'limitations':'The backing sits1.6mm above the bed on generated automatic supports. A5mm brim is configured, not guaranteed to be generated. Fresh slice/path evidence is separate; physical adhesion, fit, support removal, strength and print quality remain unverified.'}
    report_path.parent.mkdir(parents=True,exist_ok=True)
    report_path.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--source',type=Path,default=SOURCE)
    parser.add_argument('--output',type=Path,default=HERE/'AirDock60_BambuStudio.3mf')
    parser.add_argument('--report',type=Path)
    args = parser.parse_args()
    main(args.source,args.output,args.report)
