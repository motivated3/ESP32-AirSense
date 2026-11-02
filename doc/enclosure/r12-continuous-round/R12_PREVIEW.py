"""Render actual STEP models and actual straight/corner cross sections."""
import os
os.environ.setdefault('MPLCONFIGDIR', '/private/tmp/air-monitor-matplotlib')
from pathlib import Path
import importlib.util
import cadquery as cq
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager
import numpy as np
import vtk
from vtk.util.numpy_support import vtk_to_numpy
from OCP.BRepAlgoAPI import BRepAlgoAPI_Section
from OCP.gp import gp_Pln, gp_Pnt, gp_Dir

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('r12_render_reference', HERE.parent/'r11-locating-lip/R11_COVER_preview.py')
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)
font_manager.fontManager.addfont('/System/Library/Fonts/STHeiti Medium.ttc')
plt.rcParams['font.family'] = font_manager.FontProperties(fname='/System/Library/Fonts/STHeiti Medium.ttc').get_name()
BG, OLD, NEW = '#f4f6f7', '#87939a', '#218699'


def render(shape):
    scene = vtk.vtkRenderer(); scene.SetBackground(244/255, 246/255, 247/255)
    scene.AddActor(helper.actor(shape, (.30, .43, .48)))
    scene.SetUseFXAA(True)
    camera = scene.GetActiveCamera(); camera.SetFocalPoint(0, 0, 5.3)
    camera.SetPosition(80, -120, 115); camera.SetViewUp(0, 0, 1)
    camera.ParallelProjectionOn(); camera.SetParallelScale(29)
    scene.ResetCameraClippingRange()
    window = vtk.vtkRenderWindow(); window.SetOffScreenRendering(1)
    window.SetSize(1100, 800); window.SetMultiSamples(8); window.AddRenderer(scene); window.Render()
    capture = vtk.vtkWindowToImageFilter(); capture.SetInput(window)
    capture.SetInputBufferTypeToRGB(); capture.ReadFrontBufferOff(); capture.Update()
    w,h,_ = capture.GetOutput().GetDimensions()
    result = np.flipud(vtk_to_numpy(capture.GetOutput().GetPointData().GetScalars()).reshape(h,w,3)).copy()
    window.Finalize(); return result


def section(shape, corner=False):
    origin, normal = ((10.8,14.6,0),(-3.4,1.2,0)) if corner else ((0,0,0),(0,1,0))
    cut = BRepAlgoAPI_Section(shape.wrapped, gp_Pln(gp_Pnt(*origin),gp_Dir(*normal)), True)
    assert cut.IsDone()
    lines = []
    for edge in cq.Shape.cast(cut.Shape()).Edges():
        points = [edge.positionAt(float(u)) for u in np.linspace(0,1,max(2,int(edge.Length()/.015)))]
        if corner:
            lines.append(np.array([[(p.x-10.8)*1.2/np.sqrt(13)+(p.y-14.6)*3.4/np.sqrt(13), p.z] for p in points]))
        else:
            lines.append(np.array([[p.x,p.z] for p in points]))
    return lines


def main():
    old = cq.importers.importStep(str(HERE.parent/'r11-locating-lip/R11_COVER.step')).val()
    new = cq.importers.importStep(str(HERE/'R12_COVER.step')).val()
    fig = plt.figure(figsize=(14,10), facecolor=BG)
    grid = fig.add_gridspec(2,2, height_ratios=[1.2,1], left=.055, right=.97, top=.91, bottom=.115, hspace=.28, wspace=.17)
    for i,(shape,title) in enumerate(((old,'上一版 R11'),(new,'新版 R12 · 四角也一起变圆'))):
        ax = fig.add_subplot(grid[0,i]); ax.imshow(render(shape)); ax.set_axis_off()
        ax.set_title(title, fontsize=16, color='#24353d')
    for i,corner in enumerate((False,True)):
        ax = fig.add_subplot(grid[1,i]); ax.set_facecolor('white')
        for shape,color,label,style in ((old,OLD,'R11','--'),(new,NEW,'R12','-')):
            for j,line in enumerate(section(shape,corner)):
                ax.plot(line[:,0],line[:,1],color=color,lw=2.4,ls=style,label=label if j==0 else None)
        if corner:
            ax.set(xlim=(5.7,8.05),ylim=(9.1,11.8))
            ax.set_title('四角剖面：外 R0.6 → R1.0',fontsize=14)
            ax.text(5.78,9.35,'孔口仍保持 Ø4.8\n螺丝承压座保持原位',fontsize=10,color='#52636d')
            ax.set_xlabel('沿四角径向 / mm')
        else:
            ax.set(xlim=(15.9,18.9),ylim=(8.9,11.8))
            ax.set_title('直边剖面：外 R1.2 → R2.0',fontsize=14)
            ax.text(16.02,9.05,'内侧 R0.5 → R0.8',fontsize=11,color=NEW)
            ax.set_xlabel('X / mm')
        ax.set_ylabel('Z / mm'); ax.set_aspect('equal'); ax.grid(color='#e4e9ec',lw=.7)
        ax.legend(loc='upper left',frameon=False,fontsize=10)
        for spine in ax.spines.values(): spine.set_color('#dce3e6')
    fig.text(.5,.962,'后背整圈圆滑过渡｜从实际 STEP 模型提取',ha='center',fontsize=21,color='#24353d')
    fig.text(.5,.055,'直边 R2 平滑渐变到四角 R1；四角均有圆弧，8 处交界切向连续。',ha='center',fontsize=12,color='#425862')
    fig.text(.5,.025,'底板、孔位、柱脚和接缝定位止口保持；四角受螺丝孔口余量限制，不能直接套用 R2。',ha='center',fontsize=10,color='#61747e')
    target=HERE/'R12_comparison.png'; fig.savefig(target,dpi=160,facecolor=BG); plt.close(fig); print(target)


if __name__ == '__main__': main()
