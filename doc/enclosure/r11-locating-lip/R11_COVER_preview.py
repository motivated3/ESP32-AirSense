"""Render actual R11 STEP additions and a measured Y=8.5 mm cross section."""
import os
os.environ.setdefault('MPLCONFIGDIR','/private/tmp/air-monitor-matplotlib')
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
from OCP.gp import gp_Pln,gp_Pnt,gp_Dir

OUT=Path(__file__).resolve().parent
FONT=Path('/System/Library/Fonts/Supplemental/Arial Unicode.ttf')
if FONT.exists():
    font_manager.fontManager.addfont(str(FONT))
    plt.rcParams['font.family']=font_manager.FontProperties(fname=str(FONT)).get_name()
BG='#f3f5f6'
ORANGE='#db681b'


def actor(shape,color):
    vertices,triangles=shape.tessellate(.025,.08)
    pts,cells=vtk.vtkPoints(),vtk.vtkCellArray()
    for p in vertices:pts.InsertNextPoint(p.x,p.y,p.z)
    for triangle in triangles:
        cells.InsertNextCell(3)
        for v in triangle:cells.InsertCellPoint(v)
    poly=vtk.vtkPolyData();poly.SetPoints(pts);poly.SetPolys(cells)
    normals=vtk.vtkPolyDataNormals();normals.SetInputData(poly)
    normals.ConsistencyOn();normals.AutoOrientNormalsOn();normals.SetFeatureAngle(35)
    mapper=vtk.vtkPolyDataMapper();mapper.SetInputConnection(normals.GetOutputPort())
    obj=vtk.vtkActor();obj.SetMapper(mapper)
    prop=obj.GetProperty();prop.SetColor(*color);prop.SetAmbient(.25);prop.SetDiffuse(.75)
    prop.SetSpecular(.08);prop.SetSpecularPower(18)
    return obj


def render(old,added):
    scene=vtk.vtkRenderer();scene.SetBackground(243/255,245/255,246/255)
    scene.AddActor(actor(old,(.31,.34,.37)));scene.AddActor(actor(added,(.91,.36,.08)))
    scene.SetUseFXAA(True)
    camera=scene.GetActiveCamera();camera.SetFocalPoint(0,0,5.3)
    camera.SetPosition(90,-144,-125);camera.SetViewUp(0,0,1)
    camera.ParallelProjectionOn();camera.SetParallelScale(30.5)
    scene.ResetCameraClippingRange()
    window=vtk.vtkRenderWindow();window.SetOffScreenRendering(1)
    window.SetSize(1200,1100);window.SetMultiSamples(8);window.AddRenderer(scene);window.Render()
    capture=vtk.vtkWindowToImageFilter();capture.SetInput(window)
    capture.SetInputBufferTypeToRGB();capture.ReadFrontBufferOff();capture.Update()
    w,h,_=capture.GetOutput().GetDimensions()
    pixels=vtk_to_numpy(capture.GetOutput().GetPointData().GetScalars())
    result=np.flipud(pixels.reshape(h,w,3)).copy();window.Finalize()
    return result


def section(shape,y=8.5):
    cut=BRepAlgoAPI_Section(shape.wrapped,gp_Pln(gp_Pnt(0,y,0),gp_Dir(0,1,0)),True)
    assert cut.IsDone()
    lines=[]
    for edge in cq.Shape.cast(cut.Shape()).Edges():
        n=2 if edge.geomType()=='LINE' else max(12,int(edge.Length()/.04))
        points=[edge.positionAt(float(t)) for t in np.linspace(0,1,n)]
        lines.append(np.array([[p.x,p.z] for p in points]))
    return lines


def main():
    old=cq.importers.importStep(str(OUT.parent/'r10-rounded-back/R10_COVER.step')).val()
    new=cq.importers.importStep(str(OUT/'R11_COVER.step')).val()
    base=cq.importers.importStep(str(OUT.parent/'r8-wide-base/R8_BASE.step')).val()
    added=new.cut(old)
    fig=plt.figure(figsize=(14,7.7),facecolor=BG)
    grid=fig.add_gridspec(1,2,width_ratios=[1.45,1],left=.015,right=.97,bottom=.16,top=.88,wspace=.08)
    ax=fig.add_subplot(grid[0,0]);ax.imshow(render(old,added));ax.set_axis_off()
    ax.set_title('六段短插边｜橙色为新增部分',fontsize=15,pad=5)
    ax=fig.add_subplot(grid[0,1]);ax.set_facecolor(BG)
    for shape,color,label in [(old,'#6c7780','R10 原外罩'),(base,'#4388a7','R8 底板'),(added,ORANGE,'新增插边')]:
        for i,line in enumerate(section(shape)):
            ax.plot(line[:,0],line[:,1],color=color,lw=2,label=label if i==0 else None)
    ax.axhline(0,color='#8c969d',ls='--',lw=.8)
    ax.text(18.36,.06,'原接合面\nZ=0',fontsize=9,color='#58646d',ha='center')
    ax.set(xlim=(15.9,19.15),ylim=(-1.15,1.15),xlabel='X / mm',ylabel='Z / mm')
    ax.set_aspect('equal',adjustable='box');ax.grid(color='#dce2e6',lw=.6)
    ax.set_title('右侧插边截面｜Y=8.5 mm',fontsize=14,pad=12)
    ax.annotate('',xy=(17.5,-.4),xytext=(16.9,-.4),arrowprops={'arrowstyle':'<->','color':ORANGE,'lw':1.1})
    ax.text(17.2,-.28,'厚 0.6',color=ORANGE,fontsize=9,ha='center')
    ax.annotate('',xy=(18.15,0),xytext=(18.15,-.8),arrowprops={'arrowstyle':'<->','color':ORANGE,'lw':1.1})
    ax.text(18.23,-.5,'插入\n0.8',color=ORANGE,fontsize=9)
    ax.annotate('板侧模型间隙 0.20 mm',xy=(16.8,-.55),xytext=(16.0,.84),fontsize=9,
                color='#326a82',arrowprops={'arrowstyle':'->','color':'#4388a7'})
    ax.annotate('外侧 0.2 导入\n底端仍厚 0.4',xy=(17.39,-.7),xytext=(16.95,-1.03),fontsize=9,
                color=ORANGE,arrowprops={'arrowstyle':'->','color':ORANGE})
    ax.legend(loc='upper center',bbox_to_anchor=(.5,-.15),ncol=3,fontsize=9,frameon=False)
    fig.text(.5,.95,'R11 分段定位插边｜实际 STEP 几何',ha='center',fontsize=19,color='#243039')
    fig.text(.5,.075,'插边厚0.6 mm、下伸0.8 mm；45°肩台在接合面以上连接原外壁。四角和BAT走线区留空。',ha='center',fontsize=11,color='#596773')
    fig.text(.5,.035,'0.20 mm是与R8模型的实算间隙；原屏幕壳内壁未实测建模，仍需试装。',ha='center',fontsize=10,color='#596773')
    target=OUT/'R11_COVER_preview.png';fig.savefig(target,dpi=180,facecolor=BG);plt.close(fig);print(target)


if __name__=='__main__':main()
