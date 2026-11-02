"""Package R12 with the fitted R8 mesh and an installed ordinary PETG preset.

Generate geometry/project files only; no slicing or printer communication.
"""
from pathlib import Path
import hashlib
import importlib.util
import json
import xml.etree.ElementTree as ET
from zipfile import ZipFile, ZIP_DEFLATED

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('r12_pack_reference', HERE.parent/'r9-cover-refine/R9_PAIR_pack.py')
pack = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pack)
spec = importlib.util.spec_from_file_location('r12_mesh_reference', HERE.parent/'r6-fit-revision/R6_FIT_pack_3mf.py')
mesh_pack = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mesh_pack)


def generic_petg():
    folder = Path('/Applications/BambuStudio.app/Contents/Resources/profiles/BBL/filament')
    sources, visiting = {}, set()
    def resolve(name):
        assert name not in visiting
        visiting.add(name)
        path = folder/(name+'.json')
        child = json.loads(path.read_text())
        sources[name] = hashlib.sha256(path.read_bytes()).hexdigest()
        result = resolve(child['inherits']) if child.get('inherits') else {}
        includes = child.get('include', [])
        for included in ([includes] if isinstance(includes, str) else includes):
            result.update(resolve(included))
        result.update({k:v for k,v in child.items() if k not in ('inherits', 'include')})
        visiting.remove(name)
        return result
    return resolve('Generic PETG @BBL H2D'), sources


def main():
    source = HERE.parent/'r11-locating-lip/R11_PETG_HF_PAIR_BambuStudio.3mf'
    with ZipFile(source) as archive:
        entries = {n:archive.read(n) for n in archive.namelist()}
    project = json.loads(entries['Metadata/project_settings.config'])
    profile, sources = generic_petg()
    preset_metadata = {'name','from','type','setting_id','instantiation','filament_id','compatible_printers','version'}
    for key in (project.keys() & profile.keys()) - preset_metadata:
        project[key] = profile[key]
    project.pop('pre_start_fan_time', None)
    project.update({'filament_settings_id':[profile['name']], 'filament_ids':[profile['filament_id']],
                    'filament_colour':['#515151'], 'filament_multi_colour':['#515151'],
                    'enable_prime_tower':'0', 'wall_generator':'arachne'})
    assert project['filament_ids'] == ['GFG99']
    for key, value in {'nozzle_temperature':'255', 'textured_plate_temp':'70',
                       'filament_max_volumetric_speed':'12'}.items():
        assert set(project[key]) == {value}
    assert project['different_settings_to_system'][0] == 'enable_arc_fitting;enable_prime_tower;enable_support;support_type;wall_generator'
    vertices, triangles, mesh_report = mesh_pack.read_binary_stl(HERE/'R12_COVER.stl')
    vertices = [(x, -y, 11.4-z) for x,y,z in vertices]
    cover = ET.fromstring(entries['3D/Objects/object_2.model'])
    mesh = cover.find(f'.//{pack.tag("mesh")}')
    for child in list(mesh):
        mesh.remove(child)
    vs, ts = ET.SubElement(mesh, pack.tag('vertices')), ET.SubElement(mesh, pack.tag('triangles'))
    for x,y,z in vertices:
        ET.SubElement(vs, pack.tag('vertex'), x=f'{x:.5f}', y=f'{y:.5f}', z=f'{z:.5f}')
    for a,b,c in triangles:
        ET.SubElement(ts, pack.tag('triangle'), v1=str(a), v2=str(b), v3=str(c))
    model = ET.fromstring(entries['3D/3dmodel.model'])
    for md in model.findall(pack.tag('metadata')):
        if md.get('name') == 'Title':
            md.text = 'R8 fitted base + R12 continuous rounded cover; Generic PETG'
    # The GUI-saved R11 mesh was centered at Z=-6.1..6.1; the replacement
    # already rests at Z=0, so do not inherit its former +6.1 build lift.
    cover_item = model.find(f"{pack.tag('build')}/{pack.tag('item')}[@objectid='4']")
    cover_item.set('transform', '1 0 0 0 1 0 0 0 1 200 160 0')
    settings = ET.fromstring(entries['Metadata/model_settings.config'])
    cover_cfg = settings.find("object[@id='4']")
    for md in cover_cfg.iter('metadata'):
        if md.get('key') == 'name':
            md.set('value', 'R12_COVER_ONLY')
        if md.get('key') == 'source_file':
            md.set('value', 'R12_COVER.stl')
        if md.get('face_count') is not None:
            md.set('face_count', str(len(triangles)))
    for stat in cover_cfg.iter('mesh_stat'):
        stat.set('face_count', str(len(triangles)))
    for md in list(settings.find('plate').findall('metadata')):
        if md.get('key') in ('thumbnail_file','thumbnail_no_light_file','top_file','pick_file'):
            settings.find('plate').remove(md)
    rels = ET.fromstring(entries['_rels/.rels'])
    for item in list(rels):
        if item.get('Target') != '/3D/3dmodel.model':
            rels.remove(item)
    # Explicit allowlist discards all stale slice results, old thumbnails and old toolpaths.
    keep = ('[Content_Types].xml','3D/Objects/object_1.model','3D/_rels/3dmodel.model.rels')
    output = {n:entries[n] for n in keep}
    output.update({'3D/Objects/object_2.model':pack.xml(cover),
                   '3D/3dmodel.model':pack.xml(model), 'Metadata/model_settings.config':pack.xml(settings),
                   'Metadata/project_settings.config':json.dumps(project,ensure_ascii=False,indent=2).encode(),
                   '_rels/.rels':pack.xml(rels)})
    reports = []
    for only_cover in (False, True):
        current = dict(output)
        if only_cover:
            single_model = ET.fromstring(current['3D/3dmodel.model'])
            resources, build = single_model.find(pack.tag('resources')), single_model.find(pack.tag('build'))
            resources.remove(resources.find(f"{pack.tag('object')}[@id='2']"))
            build.remove(build.find(f"{pack.tag('item')}[@objectid='2']"))
            for md in single_model.findall(pack.tag('metadata')):
                if md.get('name') == 'Title':
                    md.text = 'R12 continuous rounded cover only; Generic PETG'
            single_settings = ET.fromstring(current['Metadata/model_settings.config'])
            single_settings.remove(single_settings.find("object[@id='2']"))
            plate = single_settings.find('plate')
            for item in list(plate.findall('model_instance')):
                if item.find("metadata[@key='object_id']").get('value') == '2':
                    plate.remove(item)
            assemble = single_settings.find('assemble')
            for item in list(assemble):
                if item.get('object_id') == '2':
                    assemble.remove(item)
            relationships = ET.fromstring(current['3D/_rels/3dmodel.model.rels'])
            for item in list(relationships):
                if item.get('Target') == '/3D/Objects/object_1.model':
                    relationships.remove(item)
            current.update({'3D/3dmodel.model':pack.xml(single_model),
                            'Metadata/model_settings.config':pack.xml(single_settings),
                            '3D/_rels/3dmodel.model.rels':pack.xml(relationships)})
            current.pop('3D/Objects/object_1.model')
        target = HERE/f'R12_GENERIC_PETG_{"COVER" if only_cover else "PAIR"}_BambuStudio.3mf'
        with ZipFile(target, 'w', ZIP_DEFLATED) as archive:
            for name,data in current.items():
                archive.writestr(name,data)
        with ZipFile(target) as archive:
            assert archive.testzip() is None
            assert not any(n.endswith('.gcode') for n in archive.namelist())
            assert pack.mesh_data(ET.fromstring(archive.read('3D/Objects/object_2.model')))[1] == [tuple(t) for t in triangles]
            if not only_cover:
                assert archive.read('3D/Objects/object_1.model') == entries['3D/Objects/object_1.model']
            loaded = ET.fromstring(archive.read('3D/3dmodel.model'))
            build = loaded.find(pack.tag('build'))
            count = len(build)
            assert count == (1 if only_cover else 2)
            item = build.find(f"{pack.tag('item')}[@objectid='4']")
            transform = list(map(float, item.get('transform').split()))
            assert transform == [1,0,0,0,1,0,0,0,1,200,160,0]
            saved_vertices = pack.mesh_data(ET.fromstring(archive.read('3D/Objects/object_2.model')))[0]
            assert abs(min(v[2] for v in saved_vertices)+transform[-1]) < 1e-5
            assert abs(max(v[2] for v in saved_vertices)+transform[-1]-12.2) < 1e-5
        reports.append({'file':target.name,'objects':count,'sha256':hashlib.sha256(target.read_bytes()).hexdigest()})
    report = {'projects':reports,'cover_mesh':mesh_report,'r8_mesh_preserved':True,
              'profile':profile['name'],'official_profile_sources_sha256':sources,
              'printer':project['printer_model'],'right_extruder_map':'2','nozzle_c':255,'texture_pei_c':70,
              'max_volumetric_mm3_s':12,'process':'0.20 Standard, Arachne, normal(auto)',
              'toolpaths_included':False,'gui_sliced':False,'print_sent':False}
    (HERE/'R12_PACK_check.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()
