"""Check exported H2D PETG/support G-code without operating the printer.

T0/T1 select material IDs. filament_map=2,1 maps those materials to right/left.
Interface buckets are only print-space bounding boxes, not contact-zone proof.
"""
from collections import defaultdict
from pathlib import Path
import argparse
import hashlib
import json
import math
import re

HERE = Path(__file__).resolve().parent
NUMBER = r'[-+]?(?:\d*\.\d+|\d+\.?\d*)'


def duration(value):
    units = {'d': 86400, 'h': 3600, 'm': 60, 's': 1}
    tokens = re.findall(r'(\d+(?:\.\d+)?)\s*([dhms])', value)
    assert tokens, f'Unrecognized duration: {value}'
    return sum(float(n)*units[u] for n, u in tokens)


def extents(records):
    if not records:
        return None
    points = [r[k] for r in records for k in ('a_xyz', 'b_xyz')]
    return [[min(p[i] for p in points), max(p[i] for p in points)] for i in range(3)]


def check(path, bounds_path=HERE/'AirDock60_PACK_check.json'):
    path, bounds_path = Path(path), Path(bounds_path)
    raw = path.read_bytes()
    text = raw.decode('utf-8')
    config = dict(re.findall(r'^; ([A-Za-z0-9_]+) = (.*)$', text, re.M))
    expected = {'filament_ids': 'GFG99;GFS05', 'filament_map': '2,1',
                'filament_is_support': '0,1', 'filament_map_mode': 'Manual',
                'support_filament': '1', 'support_interface_filament': '2',
                'support_top_z_distance': '0', 'support_interface_spacing': '0',
                'support_interface_not_for_body': '1', 'nozzle_temperature': '255,220',
                'nozzle_temperature_initial_layer': '255,220',
                'bed_temperature_formula': 'by_highest_temp', 'enable_arc_fitting': '0',
                'flush_into_objects': '0', 'flush_into_infill': '0', 'flush_into_support': '0'}
    for key, value in expected.items():
        assert config.get(key) == value, (key, config.get(key), value)
    assert config['support_type'] in ('normal(auto)', 'normal(manual)')

    def header(pattern):
        match = re.search(pattern, text, re.M)
        assert match, pattern
        return match[1]

    weights = list(map(float, header(r'^; total filament weight \[g\] : (.*)$').split(',')))
    volumes = list(map(float, header(r'^; total filament volume \[cm\^3\] : (.*)$').split(',')))
    densities = list(map(float, header(r'^; filament_density: (.*)$').split(',')))
    diameters = list(map(float, header(r'^; filament_diameter: (.*)$').split(',')))
    assert all(len(v) == 2 for v in (weights, volumes, densities, diameters))
    assert all(v > 0 for seq in (weights, volumes, densities, diameters) for v in seq)
    # Bambu's cm^3-labelled values here are numerically mm^3; verify by mass.
    assert all(abs(v*d/1000-w) < .03 for v, d, w in zip(volumes, densities, weights))
    area = [math.pi*(d/2)**2 for d in diameters]
    times = re.search(r'^; model printing time: (.*?); total estimated time: (.*)$', text, re.M)
    assert times
    model_seconds, total_seconds = map(duration, times.groups())
    assert 0 < model_seconds <= total_seconds
    header_layers = int(header(r'^; total layer number: (\d+)$'))

    xyz = dict.fromkeys('XYZ', 0.)
    last_e = defaultdict(float)
    absolute_xyz, relative_e = True, False
    tool, layer, height = 0, 0, None
    feature, tower, machine = 'Custom', False, None
    temps, bed = {}, None
    stats = defaultdict(lambda: {'moves': 0, 'length_mm': 0.})
    deposits, switches, ignored_custom, violations = [], [], [], []
    for number, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if line == '; MACHINE_START_GCODE_START': machine = 'start'
        if line == '; MACHINE_START_GCODE_END': machine = None
        if line == '; MACHINE_END_GCODE_START': machine = 'end'
        if line.startswith('; CHANGE_LAYER'): layer += 1
        if line.startswith('; Z_HEIGHT:'): height = float(line.split(':', 1)[1])
        if line.startswith('; FEATURE:'): feature = line.split(':', 1)[1].strip()
        if line == '; WIPE_TOWER_START': tower = True
        if line == '; WIPE_TOWER_END': tower = False
        command = line.split(';', 1)[0].strip()
        if not command:
            continue
        code = command.split()[0]
        values = {k: float(v) for k, v in re.findall(r'([XYZEST])('+NUMBER+r')', command)}
        if code == 'M83': relative_e = True
        elif code == 'M82': relative_e = False
        elif code == 'G90': absolute_xyz = True
        elif code == 'G91': absolute_xyz = False
        elif code in ('T0', 'T1'):
            tool = int(code[1:])
            switches.append({'line': number, 'material_id': tool, 'layer': layer, 'height_mm': height})
        if code in ('M104', 'M109') and 'S' in values:
            temps[int(values.get('T', tool))] = values['S']
        elif code in ('M140', 'M190') and 'S' in values:
            bed = values['S']
        if code == 'G92':
            if 'E' in values: last_e[tool] = values['E']
            for axis in xyz:
                if axis in values: xyz[axis] = values[axis]
            continue
        if code not in ('G0', 'G1', 'G2', 'G3'):
            continue
        end = {k: (values.get(k, xyz[k]) if absolute_xyz else xyz[k]+values.get(k, 0.)) for k in xyz}
        e = values.get('E', 0.) if relative_e else values.get('E', last_e[tool])-last_e[tool]
        if 'E' in values: last_e[tool] = values['E']
        xy_length = math.hypot(end['X']-xyz['X'], end['Y']-xyz['Y'])
        if e > 0 and xy_length > 1e-7:
            if machine or not layer:
                ignored_custom.append({'line': number, 'scope': machine or 'pre-layer startup',
                                       'material_id': tool, 'extrusion_mm': e})
            else:
                kind = 'Prime tower' if tower else feature
                record = {'line': number, 'material_id': tool, 'feature': kind, 'layer': layer,
                          'height_mm': height, 'a_xyz': list(xyz.values()), 'b_xyz': list(end.values()),
                          'extrusion_mm': e, 'nozzle_target_c': temps.get(tool), 'bed_target_c': bed}
                deposits.append(record)
                stats[tool, kind]['moves'] += 1
                stats[tool, kind]['length_mm'] += e
                if code not in ('G0', 'G1'):
                    violations.append({'line': number, 'kind': 'unhandled_extruding_arc', 'command': code})
                if kind == 'Custom':
                    violations.append({'line': number, 'kind': 'unclassified_custom_deposition_inside_print'})
                if tool == 1 and kind not in ('Support interface', 'Prime tower'):
                    violations.append({'line': number, 'kind': 'support_material_outside_interface_or_tower', 'feature': kind})
                if kind == 'Support interface' and tool != 1:
                    violations.append({'line': number, 'kind': 'interface_wrong_material'})
                if kind not in ('Support interface', 'Prime tower', 'Custom') and tool != 0:
                    violations.append({'line': number, 'kind': 'model_or_skeleton_wrong_material', 'feature': kind})
                if kind not in ('Prime tower', 'Custom'):
                    expected_temp = 220 if tool == 1 else 255
                    if temps.get(tool) != expected_temp:
                        violations.append({'line': number, 'kind': 'deposition_temperature', 'actual': temps.get(tool), 'expected': expected_temp})
                    if bed != 70:
                        violations.append({'line': number, 'kind': 'deposition_bed_temperature', 'actual': bed})
        xyz = end
    assert layer == header_layers and layer > 0, (layer, header_layers)
    assert deposits and not violations, violations[:20]
    assert stats[0, 'Support']['moves'] > 0 and stats[1, 'Support interface']['moves'] > 0
    assert sum(v['moves'] for (t, f), v in stats.items() if t == 0 and f not in ('Support', 'Prime tower', 'Custom')) > 0
    feature_stats = []
    for (material, kind), data in sorted(stats.items()):
        volume = data['length_mm']*area[material]
        feature_stats.append({'material_id': material, 'physical_nozzle': 'right' if material == 0 else 'left',
                              'feature': kind, 'moves': data['moves'],
                              'positive_xy_extrusion_length_mm': data['length_mm'],
                              'positive_xy_extrusion_volume_mm3': volume,
                              'derived_mass_g': volume*densities[material]/1000})
    bounds = json.loads(bounds_path.read_text())
    interfaces = [r for r in deposits if r['feature'] == 'Support interface']
    buckets = defaultdict(list)
    for record in interfaces:
        mid = [(a+b)/2 for a, b in zip(record['a_xyz'], record['b_xyz'])]
        names = [p['part'] for p in bounds['parts']
                 if all(lo-.6 <= mid[i] <= hi+.6 for i, (lo, hi) in enumerate(p['world_bounds_mm']))]
        buckets[names[0] if len(names) == 1 else 'unclassified'].append(record)
    def bucket(data):
        return {'moves': len(data), 'xyz_extents_mm': extents(data),
                'layer_heights_mm': sorted({r['height_mm'] for r in data}),
                'extruded_volume_mm3': sum(r['extrusion_mm']*area[r['material_id']] for r in data)}
    return {'source_gcode': str(path.resolve()), 'sha256': hashlib.sha256(raw).hexdigest(),
            'tool_semantics': 'T0=PETG material 1 mapped to right; T1=Support material 2 mapped to left. T IDs are material IDs, not nozzle-side names.',
            'config_verified': {k: config[k] for k in (*expected, 'support_type', 'support_style')},
            'total_layers': layer, 'model_estimated_s': model_seconds, 'total_estimated_s': total_seconds,
            'header_material_weights_g': dict(zip(('PETG', 'Support'), weights)),
            'header_material_volumes_mm3': dict(zip(('PETG', 'Support'), volumes)),
            'header_volume_unit_note': 'Header says cm^3; numerical values independently match mm^3 using density and mass.',
            'positive_xy_deposition_feature_stats': feature_stats,
            'interface_summary': bucket(interfaces),
            'interface_print_space_bounding_box_buckets': {name: bucket(data) for name, data in sorted(buckets.items())},
            'bounds_source': str(bounds_path.resolve()),
            'bounds_source_sha256': hashlib.sha256(bounds_path.read_bytes()).hexdigest(),
            'interface_segments': interfaces,
            'unclassified_interface_segments': buckets.get('unclassified', []),
            'bucket_scope': 'Midpoint in object print-space bounding box with 0.6 mm allowance only. Not an intended-contact or full support-coverage claim; bottom interfaces and scaffold flare may be unclassified. Review XYZ extents and segments against CAD.',
            'observed_deposition_temperature_targets': sorted({(r['material_id'], r['feature'], r['nozzle_target_c'], r['bed_target_c']) for r in deposits}),
            'tool_select_events': switches, 'ignored_known_custom_start_end_xy_extrusions': ignored_custom,
            'normal_body_all_PETG': True, 'support_skeleton_all_PETG': True,
            'support_material_only_interface_and_prime_tower': True,
            'model_and_contact_deposition_targets_verified': True,
            'temperature_scope': 'G-code setpoints during deposition, not measured temperatures. Prime-tower/purge/preheat/standby targets may differ.',
            'violations': violations, 'print_sent': False,
            'limitations': 'Static G0/G1 path/material/setpoint checks only; no execution of machine conditionals, geometry/support coverage proof, actual material loading, bed clearance, strength or removal-quality verification. Positive XY extrusion totals exclude E-only purges, retractions and vendor macros; they are not total net filament use.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('gcode', type=Path)
    parser.add_argument('--output', type=Path, default=HERE/'AirDock60_SUPPORT_toolpath_check.json')
    parser.add_argument('--bounds', type=Path, default=HERE/'AirDock60_PACK_check.json')
    args = parser.parse_args()
    result = check(args.gcode, args.bounds)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps({k: result[k] for k in ('sha256', 'total_layers', 'total_estimated_s',
          'header_material_weights_g', 'interface_summary', 'interface_print_space_bounding_box_buckets', 'violations')},
          ensure_ascii=False, indent=2))
