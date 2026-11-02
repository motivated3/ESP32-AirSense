"""Package the two R6 revision STL meshes as a geometry-only 3MF project.

No printer profile, toolpath, or claim of physical fit is supplied. Both parts
are placed side by side with their interiors facing up for visual inspection.
"""
from collections import Counter
import argparse
import hashlib
import json
import math
from pathlib import Path
import struct
import xml.etree.ElementTree as ET
from zipfile import ZipFile, ZIP_DEFLATED

NS = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
ET.register_namespace("", NS)


def node(parent, tag, **attrs):
    return ET.SubElement(parent, f"{{{NS}}}{tag}", {k:str(v) for k,v in attrs.items()})


def read_binary_stl(path):
    raw = path.read_bytes()
    count = struct.unpack_from("<I", raw, 80)[0]
    assert len(raw) == 84 + 50 * count, "Expected binary STL"
    vertices, triangles, index = [], [], {}
    for i in range(count):
        values = struct.unpack_from("<12fH", raw, 84 + 50*i)
        tri = []
        for j in (3, 6, 9):
            p = tuple(round(v, 5) for v in values[j:j+3])
            if p not in index:
                index[p] = len(vertices); vertices.append(p)
            tri.append(index[p])
        assert len(set(tri)) == 3, "Degenerate triangle after vertex welding"
        triangles.append(tri)
    edges = Counter(tuple(sorted((t[a], t[b]))) for t in triangles for a,b in ((0,1),(1,2),(2,0)))
    assert all(n == 2 for n in edges.values()), "STL must be a closed manifold"
    return vertices, triangles, {"triangles":count, "vertices":len(vertices),
                                 "closed_edge_pairs":len(edges), "sha256":hashlib.sha256(raw).hexdigest()}


def main(out):
    model = ET.Element(f"{{{NS}}}model", {"unit":"millimeter", "{http://www.w3.org/XML/1998/namespace}lang":"en-US"})
    for name, value in [("Title", "R6 post +1 mm, ear 1.2 mm, cover foot setback 2.2 mm"),
                        ("Description", "Two parts: original post tops +1 mm above rim; ear underside +1 mm and top +2.2 mm; cover feet start +2.2 mm. 31.4x39 mm plate, 37.6x45.2 mm R8 cover, 24x36 mm holes, 21.6x13.4 mm SCD41 footprint. Physical fit unverified. No toolpath."),
                        ("Application", "ESP32-AirSense geometry-only fit revision")]:
        node(model, "metadata", name=name).text = value
    resources = node(model, "resources"); build = node(model, "build")
    reports = {}
    for i, (part, px) in enumerate((("baseplate",100),("cover",153)), 1):
        path = out / f"R6_FIT_{part}.stl"
        verts, tris, report = read_binary_stl(path)
        # Rotate cover 180 deg around X, then rest each part on Z=0.
        if part == "cover": verts = [(x,-y,-z) for x,y,z in verts]
        minz = min(p[2] for p in verts)
        verts = [(x,y,z-minz) for x,y,z in verts]
        if part == "cover":
            rim_z = max(p[2] for p in verts)
            setbacks = [rim_z-max(z for vx,vy,z in verts
                        if math.hypot(vx-x,vy-y) <= 2.91)
                        for x in (-12,12) for y in (-18,18)]
            assert all(abs(value-2.2) < 1e-4 for value in setbacks)
            report["printed_foot_setbacks_from_rim_mm"] = [round(v,4) for v in setbacks]
        obj = node(resources, "object", id=i, type="model", name=f"R6_FIT_{part}_NOT_FIT_VERIFIED")
        mesh = node(obj, "mesh"); vs = node(mesh, "vertices"); ts = node(mesh, "triangles")
        for x,y,z in verts: node(vs, "vertex", x=f"{x:.5f}", y=f"{y:.5f}", z=f"{z:.5f}")
        for a,b,c in tris: node(ts, "triangle", v1=a, v2=b, v3=c)
        node(build, "item", objectid=i, transform=f"1 0 0 0 1 0 0 0 1 {px} 130 0")
        report.update({"display_translation_xy":[px,130],"cover_flipped_to_show_inside":part=="cover", "minimum_z":min(p[2] for p in verts)})
        reports[part] = report
    target = out / "R6_POST1mm_CONTACT2p2mm.3mf"
    content_types = '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/></Types>'
    rels = '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Target="/3D/3dmodel.model" Id="rel0" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/></Relationships>'
    with ZipFile(target, "w", ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", content_types)
        z.writestr("_rels/.rels", rels)
        z.writestr("3D/3dmodel.model", ET.tostring(model, encoding="utf-8", xml_declaration=True))
    with ZipFile(target) as z:
        assert z.testzip() is None
        root = ET.fromstring(z.read("3D/3dmodel.model"))
        assert len(root.findall(f"{{{NS}}}resources/{{{NS}}}object")) == 2
        assert len(root.findall(f"{{{NS}}}build/{{{NS}}}item")) == 2
        assert not any("gcode" in p.lower() for p in z.namelist())
    reports.update({"project":target.name,"units":"mm", "purpose":"two-piece PLA fit trial", "objects":2,
                    "physical_fit_verified":False,"pla_trial_print_intended":True,
                    "toolpaths_included":False})
    (out / "R6_FIT_mesh-package-check.json").write_text(json.dumps(reports, ensure_ascii=False, indent=2)+"\n")
    print(json.dumps(reports, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=Path(__file__).resolve().parent)
    main(ap.parse_args().out)
