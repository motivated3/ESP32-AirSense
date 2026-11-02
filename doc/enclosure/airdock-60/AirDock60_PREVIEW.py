"""Engineering preview of the exported AirDock60 STEP parts.

The view deliberately separates actual printable geometry from the retained
R8 plate, conservative sensor envelopes and the unmeasured black front proxy.
It never exports a replacement model or communicates with a printer.
"""
import os
import sys
sys.dont_write_bytecode = True
os.environ.setdefault("MPLCONFIGDIR", "/private/tmp/air-monitor-airdock60-preview")
from pathlib import Path
import importlib.util
import json
import math

import cadquery as cq
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.patches import FancyBboxPatch
import numpy as np
import vtk
from vtk.util.numpy_support import vtk_to_numpy

HERE = Path(__file__).resolve().parent


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


g = module("airdock60_preview_geometry", HERE / "AirDock60_CAD.py")
reference = module("airdock60_preview_r12", HERE.parent / "r12-continuous-round/R12_PREVIEW.py")
actor = reference.helper.actor
font_manager.fontManager.addfont("/System/Library/Fonts/STHeiti Medium.ttc")
plt.rcParams["font.family"] = font_manager.FontProperties(
    fname="/System/Library/Fonts/STHeiti Medium.ttc").get_name()
plt.rcParams["axes.unicode_minus"] = False
BG, INK, MUTED = "#f4f6f7", "#263c37", "#65766e"
MOUNT, BAY, TRAY = (.42, .49, .46), (.62, .69, .64), (.40, .59, .49)
OLD, SCD, SFA = (.20, .43, .57), (.05, .54, .40), (.30, .62, .49)
STEEL, BRASS = (.47, .52, .55), (.78, .58, .25)


def render(parts, camera, focus, scale, size=(1250, 1000), markers=None):
    scene = vtk.vtkRenderer()
    scene.SetBackground(244 / 255, 246 / 255, 247 / 255)
    scene.SetUseFXAA(True)
    for shape, color, *extra in parts:
        if shape.Volume() < 1e-7:
            continue
        obj = actor(shape, color)
        obj.GetProperty().SetSpecular(.14)
        obj.GetProperty().SetSpecularPower(30)
        if extra:
            obj.GetProperty().SetOpacity(extra[0])
        scene.AddActor(obj)
    view = scene.GetActiveCamera()
    view.SetPosition(*camera)
    view.SetFocalPoint(*focus)
    view.SetViewUp(0, 0, 1)
    view.ParallelProjectionOn()
    view.SetParallelScale(scale)
    for position, power in [((0, -70, 100), .7), ((-70, 70, 80), .55), ((80, 30, 60), .45)]:
        light = vtk.vtkLight()
        light.SetPosition(*position)
        light.SetFocalPoint(*focus)
        light.SetIntensity(power)
        scene.AddLight(light)
    scene.ResetCameraClippingRange()
    window = vtk.vtkRenderWindow()
    window.SetOffScreenRendering(1)
    window.SetSize(*size)
    window.SetMultiSamples(8)
    window.AddRenderer(scene)
    window.Render()
    capture = vtk.vtkWindowToImageFilter()
    capture.SetInput(window)
    capture.SetInputBufferTypeToRGB()
    capture.ReadFrontBufferOff()
    capture.Update()
    w, h, _ = capture.GetOutput().GetDimensions()
    pixels = vtk_to_numpy(capture.GetOutput().GetPointData().GetScalars())
    result = np.flipud(pixels.reshape(h, w, 3)).copy()
    projected = {}
    for name, xyz in (markers or {}).items():
        scene.SetWorldPoint(*xyz, 1)
        scene.WorldToDisplay()
        x, y, _ = scene.GetDisplayPoint()
        projected[name] = (x, h - y)
    window.Finalize()
    return (result, projected) if markers is not None else result


def load_current_parts():
    assert g.REAR == 39 and g.HEIGHT == 14
    assert g.mount.BACK == 3.4 and g.mount.INNER == 2.2 and g.mount.LIFT == 2.9
    assert g.MODULES["SCD41"][2:4] == (13.4, 35.0)
    assert g.MODULES["SFA40"][2:4] == (20.0, 35.0)
    paths = {name: HERE / f"AirDock60_{name.upper()}.step" for name in ("mount", "bay", "tray")}
    latest_step = max(p.stat().st_mtime for p in paths.values())
    assert min(p.stat().st_mtime for p in paths.values()) >= (HERE / "AirDock60_CAD.py").stat().st_mtime
    check = HERE / "AirDock60_ASSEMBLY_check.json"
    assert check.exists() and check.stat().st_mtime >= latest_step, "Run the fresh exported-STEP checks before preview"
    data = json.loads(check.read_text())
    assert data["extra_backing_above_stand_mm3"] < 1e-4
    assert "tray_removal_with_bay_and_mount_held" in data, "Wait for the new tray-first removal checks"
    assert all(max(row["intersections_mm3"].values()) < 1e-4
               for row in data["tray_removal_with_bay_and_mount_held"])
    parts = {name: cq.importers.importStep(str(path)).val() for name, path in paths.items()}
    assert all(s.isValid() and len(s.Solids()) == 1 for s in parts.values())
    return parts


def front_proxy():
    # Visual body only: depth 12 mm is not an original-shell measurement.
    return g.mount.to_world(g.rounded(37.6, 45.2, 8, -12, 0))


def image_panel(fig, rect, pixels, title, subtitle, callouts=()):
    ax = fig.add_axes(rect)
    ax.imshow(pixels)
    ax.axis("off")
    for label, target, at in callouts:
        ax.annotate(label, xy=target, xytext=at, fontsize=8.2, color=INK,
                    bbox=dict(boxstyle="round,pad=.35", fc="white", ec="#cbd8d0", lw=.6),
                    arrowprops=dict(arrowstyle="->", color="#467965", lw=.8))
    x, y, w, h = rect
    fig.text(x + .012, y + h + .022, title, fontsize=16, color=INK)
    fig.text(x + .012, y + h - .010, subtitle, fontsize=9.6, color=MUTED)


def main():
    parts = load_current_parts()
    old = cq.importers.importStep(str(HERE.parent / "r8-wide-base/R8_BASE.step")).val()
    old = g.mount.to_world(old)
    screw, nut = g.screw_and_nut()
    modules = g.sensor_envelopes()
    hardware = [(screw, STEEL), (nut, BRASS)]
    # Four SYMBOLIC original screw heads above the flat plate. Their actual
    # head dimensions have not been measured; these are not fit references.
    heads = [(g.mount.to_world(g.cylinder(2.0, 3.0, 4.2, x, y)), STEEL)
             for x in (-12, 12) for y in (-18, 18)]
    # Only a short bundle segment in the channel already checked by AirDock60_CHECK.
    # No invented full route through a wall or a closed cable bore is drawn.
    wire = cq.Solid.makeCylinder(.8, 9, cq.Vector(0, 6.9, 8.5), cq.Vector(0, 1, 0))
    assert all(s.copy().intersect(wire.copy()).Volume() < 1e-4 for s in parts.values())
    def point(x, y, z):
        return g.mount.to_world(cq.Vertex.makeVertex(x, y, z)).Center().toTuple()

    assembly, assembly_points = render([
        (front_proxy(), (.11, .15, .14)), (old, OLD),
        (parts["mount"], MOUNT), (parts["bay"], BAY), (parts["tray"], TRAY), *hardware, *heads,
    ], (-85, 125, 83), (0, 15, 22), 34.5, markers={
        "flat": point(1, 9, 3), "vent": (8,27.5,14), "BAT": point(18.3, -2.8, 2.6),
        "head": point(12, 18, 4.2)})

    bay_shift, tray_shift = (0, 14, 5), (0, 14, -16)
    exploded = render([
        (old.translate((-8, -9, 5)), OLD), (parts["mount"], MOUNT),
        (parts["bay"].translate(bay_shift), BAY),
        (parts["tray"].translate(tray_shift), TRAY),
        (modules["SCD41"].translate(tray_shift), SCD),
        (modules["SFA40"].translate(tray_shift), SFA),
        (screw.translate((0, 14, -30)), STEEL), (nut, BRASS), *heads,
    ], (-95, 130, 83), (0, 18, 12), 48)

    # Section the actual solids on the bolt axis; hardware stays whole so its
    # length, trapped-nut seat and underside head are easy to distinguish.
    crop = g.box(14, 15, -.15, 12.4, g.LOCK_X - 7, g.LOCK_Y)
    detail = []
    for name, color in (("mount", MOUNT), ("bay", BAY), ("tray", TRAY)):
        clipped = parts[name].copy().intersect(crop.copy())
        if clipped.Volume() > 1e-7:
            detail.append((clipped, color))
    lock_view, wire_points = render(detail + hardware + [(wire, (.03, .66, .40))],
        (38, 45, 27), (3.3, 12.8, 5.5), 12.5, (1200, 820),
        markers={"wire": (0, 10.0, 8.5)})

    fig = plt.figure(figsize=(17.5, 13.0), facecolor=BG)
    fig.text(.045, .955, "AirDock 60 / 背板与接缝优化 · 60°", fontsize=27, color=INK)
    fig.text(.046, .918, "1.2 mm 通风背板｜1 mm 空气间隔｜机身侧周边接合边与六处定位耳", fontsize=12.5, color=MUTED)
    fig.add_artist(plt.Line2D([.045, .955], [.894, .894], transform=fig.transFigure, color="#cbd8d0", lw=1))

    image_panel(fig, [.035, .50, .455, .345], assembly,
                "01 / 实际平板结构", "灰色为新打印件；黑色前壳仅作外观代理，原四颗螺丝头为示意",
                [("1.2 mm 背板，中上部八条栅格", assembly_points["flat"], (65, 190)),
                 ("舱顶 10 条圆头栅格，连通内腔", assembly_points["vent"], (770, 450)),
                 ("原螺丝头外露", assembly_points["head"], (770, 150)),
                 ("新平板此处已补平", assembly_points["BAT"], (60, 750))])
    image_panel(fig, [.51, .50, .455, .345], exploded,
                "02 / 分件与拆装", "爆炸间距用于展示；蓝色 R8 已有底板不重印，绿色为模块保守包络")
    image_panel(fig, [.035, .145, .455, .265], lock_view,
                "03 / 下部 U 槽与锁紧剖视", "绿色仅为已检查通道内的线束片段；先放线，再用托盘合拢",
                [("U 槽底部开放，可侧放焊线", wire_points["wire"], (55, 95))])

    # Assembly instructions, rather than decorative leader lines detached from
    # the geometry. In particular the rear tray tongues are not flexible clips.
    fig.patches.append(FancyBboxPatch((.54, .14), .40, .285,
        transform=fig.transFigure, boxstyle="round,pad=.014,rounding_size=.012",
        facecolor="white", edgecolor="#d9e3dc", lw=.8))
    fig.text(.55, .396, "装配与维护", fontsize=17, color="#157454")
    notes = [
        "原 R8 保留；背板 1.2 mm，四孔承压座仍在原高度。",
        "焊线从下部开放 U 槽放入，无需端头穿孔。",
        "放入螺母、装舱与托盘；底部一颗 M2×8 锁紧。",
        "拆卸先托住舱体及托盘，退出底部单颗 M2 螺钉。",
        "托盘轻降 0.1、后退 1.0 mm，再下取，避免拉扯焊线。",
        "需要时空舱再后退 8 mm；现有焊线需保留松弛。",
    ]
    for i, line in enumerate(notes):
        fig.text(.55, .357 - i * .028, line, fontsize=10.7, color=INK)
    fig.text(.55, .184, "螺钉头包络 Ø4×1.6；M2 螺母按 4 mm 对边、1.6 mm 厚预留。", fontsize=9.8, color=MUTED)
    fig.text(.55, .157, "屏幕夹角 60°｜舱高 14 mm｜后缘坐标 Y=39，不是整机深度", fontsize=10.2, color="#157454")

    fig.text(.05, .092, "保守模块包络非原厂 STEP；原螺丝头仅为示意。平板与舱前面保留空气间隔，只有下部支架承力连接。", fontsize=10.2, color=MUTED)
    fig.text(.05, .061, "检查覆盖实体、名义干涉与采样拆装路径；原前壳、实际螺钉、成形强度、车辆固定及温升仍需实物验证。", fontsize=10.2, color=MUTED)
    fig.text(.05, .030, "仅为试装工程预览；本图不代表已打印或已完成温度校准。", fontsize=10.2, color=MUTED)
    target = HERE / "AirDock60_assembly.png"
    fig.savefig(target, dpi=180, facecolor=BG)
    plt.close(fig)
    roof_view = render([(parts["bay"], BAY)], (-55, 70, 75), (0, 24, 8), 27, (1200, 900))
    plt.imsave(HERE / "AirDock60_roof_vents.png", roof_view)
    inner, inner_points = render([(parts['mount'], MOUNT)],
        (80,-110,90), (0,10,23), 27, (1300,1100), markers={
            'rim':point(-18,0,1.8), 'tab':point(-17.2,8.5,1.0),
            'vent':point(4.5,7,2.2), 'wire':(0,6.9,7.5)})
    side, side_points = render([(parts['mount'],MOUNT),(parts['bay'],BAY),(parts['tray'],TRAY)],
        (110,17,20), (0,17,20), 24, (1300,1100), markers={
            'gap':point(-18,-11,3.9),'red_edge':point(-18,1,2.4)})
    fig=plt.figure(figsize=(15,8.2),facecolor=BG)
    fig.text(.04,.95,'AirDock 60 / 本次实际 CAD 修改',fontsize=24,color=INK)
    image_panel(fig,[.02,.16,.48,.64],inner,'01 / 朝机身一侧',
        '周边凸边 0.8 mm；六处定位耳辅助定位，四颗螺丝锁紧',[
            ('周边凸边 0.8 mm',inner_points['rim'],(65,600)),
            ('六处定位耳，凸边外再伸出 0.8 mm',inner_points['tab'],(50,120)),
            ('八条 14 × 1.4 mm 圆头通风槽',inner_points['vent'],(720,230)),
            ('底部 U 槽保持开放',inner_points['wire'],(700,900))])
    image_panel(fig,[.51,.16,.47,.64],side,'02 / 真实侧面间隔',
        '外圈总厚 2.0 mm = 板面 1.2 + 凸边 0.8；四孔承压面不动',[
            ('黄色：空气间隔仍为 1 mm',side_points['gap'],(720,650)),
            ('红线：外圈总厚 2.0 mm',side_points['red_edge'],(650,150))])
    fig.text(.04,.065,'定位耳沿用旧版接口；底部一处偏开线槽。机身内轮廓未实测建模，最终咬合、强度和降温效果仍须试装。',fontsize=11,color=MUTED)
    fig.savefig(HERE/'AirDock60_backing_detail.png',dpi=160,facecolor=BG)
    plt.close(fig)
    print(target)


if __name__ == "__main__":
    main()
