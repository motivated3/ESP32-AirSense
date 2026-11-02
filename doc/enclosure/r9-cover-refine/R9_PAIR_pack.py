"""Rebuild the fitted R8 base + refined R9 cover as one native Bambu project.

Preserve the verified R8 machine/process/PLA/right-nozzle settings and its exact
native mesh. The cover mesh already rests on the bed with its interior facing
up. This prepares files only; it never contacts or starts a printer.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import uuid
import xml.etree.ElementTree as ET
from zipfile import ZipFile, ZIP_DEFLATED

CORE = 'http://schemas.microsoft.com/3dmanufacturing/core/2015/02'
PROD = 'http://schemas.microsoft.com/3dmanufacturing/production/2015/06'
REL = 'http://schemas.openxmlformats.org/package/2006/relationships'
ET.register_namespace('', CORE)
ET.register_namespace('p', PROD)
HERE = Path(__file__).resolve().parent
IDENTITY = '1 0 0 0 1 0 0 0 1'


def tag(name):
    return f'{{{CORE}}}{name}'


def xml(root):
    # Bambu's relationship reader expects an unprefixed Relationships root.
    if root.tag.startswith('{'):
        ET.register_namespace('', root.tag[1:].split('}')[0])
    return ET.tostring(root, encoding='utf-8', xml_declaration=True)


def meta(parent, key, value):
    ET.SubElement(parent, 'metadata', key=key, value=str(value))


def mesh_data(root):
    mesh = root.find(f'.//{tag("mesh")}')
    verts = [tuple(float(v.get(a)) for a in ('x', 'y', 'z'))
             for v in mesh.find(tag('vertices'))]
    tris = [tuple(int(t.get(a)) for a in ('v1', 'v2', 'v3'))
            for t in mesh.find(tag('triangles'))]
    return verts, tris


def bounds(verts, xyz):
    return [[min(v[i] for v in verts)+xyz[i], max(v[i] for v in verts)+xyz[i]]
            for i in range(3)]


def resolved_petg_profile(target):
    """Expand only installed official preset ancestors/includes, without guessing."""
    folder = Path('/Applications/BambuStudio.app/Contents/Resources/profiles/BBL/filament')
    files = {p.stem:p for p in folder.glob('*.json')}
    visiting, sources = set(), []
    def resolve(name):
        assert name not in visiting, f'Preset cycle: {name}'
        visiting.add(name)
        path = files[name]
        child = json.loads(path.read_text())
        result = resolve(child['inherits']) if child.get('inherits') else {}
        includes = child.get('include', [])
        for include in ([includes] if isinstance(includes, str) else includes):
            result.update(resolve(include))
        result.update({k:v for k,v in child.items() if k not in ('inherits', 'include')})
        visiting.remove(name)
        if str(path) not in sources: sources.append(str(path))
        return result
    profile = resolve('Bambu PETG HF @BBL H2D 0.4 nozzle')
    profile.update({'from':'user', 'type':'filament', 'instantiation':'true'})
    expected = {'filament_type':'PETG', 'textured_plate_temp':'70',
                'textured_plate_temp_initial_layer':'70', 'nozzle_temperature':'245',
                'nozzle_temperature_initial_layer':'245', 'filament_density':'1.28',
                'filament_flow_ratio':'0.95'}
    for key, value in expected.items():
        assert set(profile[key]) == {value}, (key, profile[key])
    assert profile['filament_id'] == 'GFG02'
    assert profile['compatible_printers'] == ['Bambu Lab H2D 0.4 nozzle']
    Path(target).write_text(json.dumps(profile, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps({'resolved_preset':str(target), 'official_sources':sources,
                      'validated':expected, 'filament_id':profile['filament_id'],
                      'compatible_printers':profile['compatible_printers']}, indent=2))


def main(target, project_settings=None, color=None, *, cover_source=None,
         cover_name='R9_COVER_ONLY', cover_title='R9 refined cover'):
    template = HERE.parent/'r8-wide-base/R8_BASE_ONLY_BambuStudio.3mf'
    cover_source = Path(cover_source) if cover_source else HERE/'R9_COVER_geometry.3mf'
    with ZipFile(template) as z:
        entries = {n:z.read(n) for n in z.namelist()}
    if project_settings:
        # Accept a complete settings export from the installed Bambu CLI.
        entries['Metadata/project_settings.config'] = Path(project_settings).read_bytes()
    with ZipFile(cover_source) as z:
        cover_root = ET.fromstring(z.read('3D/3dmodel.model'))
    model = ET.fromstring(entries['3D/3dmodel.model'])
    settings = ET.fromstring(entries['Metadata/model_settings.config'])
    project = json.loads(entries['Metadata/project_settings.config'])
    if color:
        project['filament_colour'] = [color]
        entries['Metadata/project_settings.config'] = json.dumps(project, ensure_ascii=False, indent=2).encode()
    if project_settings:
        assert project['filament_type'] == ['PETG']
        assert project['filament_ids'] == ['GFG02']
        for key, value in {'textured_plate_temp':'70', 'textured_plate_temp_initial_layer':'70',
                           'nozzle_temperature':'245', 'nozzle_temperature_initial_layer':'245',
                           'filament_density':'1.28', 'filament_flow_ratio':'0.95'}.items():
            assert set(project[key]) == {value}, (key, project[key])
    base_pos, cover_pos = (145, 160, 1.5), (200, 160, 0)
    base_transform = f'{IDENTITY} '+ ' '.join(map(str, base_pos))
    cover_transform = f'{IDENTITY} '+ ' '.join(map(str, cover_pos))
    resources, build = model.find(tag('resources')), model.find(tag('build'))
    assert len(resources) == len(build) == 1
    for item in model.findall(tag('metadata')):
        if item.get('name') == 'Title':
            item.text = f'R8 fitted base + {cover_title}; two parts, '+project['filament_type'][0]
    build[0].set('transform', base_transform)
    wrapper = copy.deepcopy(resources[0]); wrapper.set('id', '4')
    wrapper.set(f'{{{PROD}}}UUID', str(uuid.uuid4()))
    component = wrapper.find(f'{tag("components")}/{tag("component")}')
    component.set('objectid', '3'); component.set(f'{{{PROD}}}path', '/3D/Objects/object_2.model')
    component.set(f'{{{PROD}}}UUID', str(uuid.uuid4())); resources.append(wrapper)
    new_item = copy.deepcopy(build[0]); new_item.set('objectid', '4')
    new_item.set('transform', cover_transform); new_item.set(f'{{{PROD}}}UUID', str(uuid.uuid4()))
    build.append(new_item)
    # Wrap the untouched print-oriented cover mesh as a native production resource.
    cover_native = ET.Element(tag('model'), unit='millimeter', requiredextensions='p')
    cover_native.set('{http://www.w3.org/XML/1998/namespace}lang', 'en-US')
    cover_res = ET.SubElement(cover_native, tag('resources'))
    cover_obj = copy.deepcopy(cover_root.find(f'{tag("resources")}/{tag("object")}'))
    cover_obj.set('id', '3'); cover_obj.set(f'{{{PROD}}}UUID', str(uuid.uuid4()))
    cover_res.append(cover_obj)
    base_verts, base_tris = mesh_data(ET.fromstring(entries['3D/Objects/object_1.model']))
    cover_verts, cover_tris = mesh_data(cover_root)
    cfg_obj = copy.deepcopy(settings.find('object')); cfg_obj.set('id', '4')
    cfg_obj.find("metadata[@key='name']").set('value', cover_name)
    cfg_obj.find('metadata[@face_count]').set('face_count', str(len(cover_tris)))
    part = cfg_obj.find('part'); part.set('id', '3'); part.set('uuid', str(uuid.uuid4()))
    replacements = {'name':cover_name, 'source_file':cover_source.name,
                    'source_offset_z':'0'}
    for key, value in replacements.items():
        part.find(f"metadata[@key='{key}']").set('value', value)
    part.find('mesh_stat').set('face_count', str(len(cover_tris)))
    settings.insert(1, cfg_obj)
    plate = settings.find('plate')
    for md in list(plate.findall('metadata')):
        if md.get('key') in ('thumbnail_file', 'thumbnail_no_light_file', 'top_file', 'pick_file'):
            plate.remove(md)
    instance = copy.deepcopy(plate.find('model_instance'))
    instance.find("metadata[@key='object_id']").set('value', '4')
    instance.find("metadata[@key='identify_id']").set('value', '1724')
    plate.append(instance)
    assemble = settings.find('assemble')
    assemble.find("assemble_item[@instance_id='0']").set('transform', base_transform)
    for source in list(assemble):
        new = copy.deepcopy(source); new.set('object_id', '4')
        if new.get('instance_id') is not None: new.set('transform', cover_transform)
        assemble.append(new)
    relations = ET.fromstring(entries['3D/_rels/3dmodel.model.rels'])
    ET.SubElement(relations, f'{{{REL}}}Relationship',
                  Target='/3D/Objects/object_2.model', Id='rel-2',
                  Type='http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel')
    root_rels = ET.fromstring(entries['_rels/.rels'])
    for item in list(root_rels):
        if item.get('Target') != '/3D/3dmodel.model': root_rels.remove(item)
    # Drop stale R8 thumbnails, slicing summaries, pick IDs and cut caches.
    keep = ['[Content_Types].xml', 'Metadata/project_settings.config', '3D/Objects/object_1.model']
    output = {n:entries[n] for n in keep}
    output.update({'3D/3dmodel.model':xml(model), '3D/Objects/object_2.model':xml(cover_native),
                   'Metadata/model_settings.config':xml(settings),
                   '3D/_rels/3dmodel.model.rels':xml(relations), '_rels/.rels':xml(root_rels)})
    target = Path(target)
    with ZipFile(target, 'w', ZIP_DEFLATED) as z:
        for name, data in output.items(): z.writestr(name, data)
    with ZipFile(target) as z:
        assert z.testzip() is None
        assert z.read('3D/Objects/object_1.model') == entries['3D/Objects/object_1.model']
        assert mesh_data(ET.fromstring(z.read('3D/Objects/object_2.model'))) == (cover_verts, cover_tris)
        assert len(ET.fromstring(z.read('3D/3dmodel.model')).find(tag('build'))) == 2
        assert len(ET.fromstring(z.read('Metadata/model_settings.config')).findall('object')) == 2
        assert z.read('Metadata/project_settings.config') == entries['Metadata/project_settings.config']
    b0, b1 = bounds(base_verts, base_pos), bounds(cover_verts, cover_pos)
    assert b0[0][1] < b1[0][0]
    assert abs(b0[2][0]) < 1e-5 and abs(b1[2][0]) < 1e-5
    assert project['printer_model'] == 'Bambu Lab H2D'
    assert project['enable_support'] == '1' and project['support_type'] == 'normal(auto)'
    assert plate.find("metadata[@key='filament_maps']").get('value') == '2'
    print(json.dumps({'output':str(target),'sha256':hashlib.sha256(target.read_bytes()).hexdigest(),
                      'objects':2,'triangle_counts':[len(base_tris),len(cover_tris)],
                      'world_bounds_mm':[b0,b1],'separation_x_mm':b1[0][0]-b0[0][1],
                      'printer':project['printer_settings_id'],'filament':project['filament_settings_id'],
                      'support':project['support_type'],'plate_filament_map':'2 (right)',
                      'native_base_mesh_byte_identical':True,'cover_mesh_identical':True}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=Path('/private/tmp/r9_pair_prepared.3mf'))
    parser.add_argument('--write-petg-preset', type=Path)
    parser.add_argument('--project-settings', type=Path)
    parser.add_argument('--color', help='Display color only, for example #515151')
    args = parser.parse_args()
    if args.write_petg_preset:
        resolved_petg_profile(args.write_petg_preset)
    else:
        main(args.output, args.project_settings, args.color)
