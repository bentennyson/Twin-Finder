"""Capture this harness's own Tk window; never read another desktop window."""
import sys,ctypes,argparse,time,json,hashlib,shutil,csv,subprocess,os
from ctypes import wintypes as W
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PIL import Image
from desktop import App
from modern_ui import create_root
import progressive,storage,twin_workflow as workflow

def capture(root,path):
    user=ctypes.WinDLL('user32',use_last_error=True);gdi=ctypes.WinDLL('gdi32',use_last_error=True)
    user.GetAncestor.argtypes=[W.HWND,W.UINT];user.GetAncestor.restype=W.HWND
    user.GetWindowRect.argtypes=[W.HWND,ctypes.POINTER(W.RECT)]
    user.GetWindowDC.argtypes=[W.HWND];user.GetWindowDC.restype=W.HDC
    user.PrintWindow.argtypes=[W.HWND,W.HDC,W.UINT]
    user.ReleaseDC.argtypes=[W.HWND,W.HDC]
    gdi.CreateCompatibleDC.argtypes=[W.HDC];gdi.CreateCompatibleDC.restype=W.HDC
    gdi.CreateCompatibleBitmap.argtypes=[W.HDC,ctypes.c_int,ctypes.c_int];gdi.CreateCompatibleBitmap.restype=W.HBITMAP
    gdi.SelectObject.argtypes=[W.HDC,W.HGDIOBJ];gdi.SelectObject.restype=W.HGDIOBJ
    gdi.GetDIBits.argtypes=[W.HDC,W.HBITMAP,W.UINT,W.UINT,ctypes.c_void_p,ctypes.c_void_p,W.UINT]
    gdi.DeleteObject.argtypes=[W.HGDIOBJ];gdi.DeleteDC.argtypes=[W.HDC]
    class Header(ctypes.Structure):
        _fields_=[('size',W.DWORD),('width',W.LONG),('height',W.LONG),('planes',W.WORD),('bits',W.WORD),('compression',W.DWORD),('bytes',W.DWORD),('xppm',W.LONG),('yppm',W.LONG),('colors',W.DWORD),('important',W.DWORD)]
    hwnd=user.GetAncestor(root.winfo_id(),2);rect=W.RECT();assert user.GetWindowRect(hwnd,ctypes.byref(rect))
    width,height=rect.right-rect.left,rect.bottom-rect.top
    dc=user.GetWindowDC(hwnd);mem=gdi.CreateCompatibleDC(dc);bitmap=gdi.CreateCompatibleBitmap(dc,width,height);previous=gdi.SelectObject(mem,bitmap)
    try:
        assert user.PrintWindow(hwnd,mem,2),'PrintWindow failed'
        header=Header(ctypes.sizeof(Header),width,-height,1,32,0,width*height*4,0,0,0,0)
        data=ctypes.create_string_buffer(width*height*4)
        gdi.SelectObject(mem,previous)
        assert gdi.GetDIBits(mem,bitmap,0,height,data,ctypes.byref(header),0)==height
        image=Image.frombuffer('RGB',(width,height),data.raw,'raw','BGRX',0,1)
        image.save(path)
    finally:
        gdi.DeleteObject(bitmap);gdi.DeleteDC(mem);user.ReleaseDC(hwnd,dc)

def main():
    parser=argparse.ArgumentParser(description='Render actual application windows for the manual using isolated scripted jobs. Windows only.')
    parser.add_argument('--work',type=Path,required=True)
    parser.add_argument('--feedback-job',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--step',type=int)
    args=parser.parse_args()
    project=Path(__file__).resolve().parents[1]
    job=args.work/'sample_job';feedback=args.work/'feedback_job'
    if args.step:
        names=['01_open','02_dataset','03_review','04_evidence','05_saved','06_feedback','07_before','08_after','09_export']
        chosen=feedback if 6<=args.step<=8 else job
        if args.step in (7,8):workflow.rollback(feedback,args.step-7)
        root=create_root();app=App(root,None if args.step==1 else chosen);root.geometry('1400x1000+20+20');root.update()
        try:
            if args.step==2:app.tabs.select(app.data_tab);app.data_summary.yview_moveto(0)
            if args.step==4:
                app.toggle_details();root.update();app.review_content.scroll_canvas.yview_moveto(1)
            if args.step==5:
                app.save_review('accept');deadline=time.monotonic()+20
                while app.review_pending and time.monotonic()<deadline:root.update();time.sleep(.02)
                assert app.review_pending is None and app.current!=1
            if args.step==6:app.tabs.select(app.learn_tab);app.refresh_counts()
            if args.step in (7,8):
                rows=list(csv.DictReader((project/'results/feedback_replay_predictions.csv').open()))
                changed=next(int(r['pair_number']) for r in rows if r['prediction_before']!=r['prediction_after'])
                app.display_pair(workflow.inspect(feedback,changed));app.tabs.select(app.review_tab)
            if args.step==9:
                app.tabs.select(app.learn_tab);app.refresh_counts()
                with storage.job_lock(job,wait=5):result=storage.export_cleaned(job,args.work/'sample_export.zip')
                app.status.set(f"Export complete · {result['output_records']} output records · sample_export.zip")
                root.update();app.learn_content.scroll_canvas.yview_moveto(1)
            end=time.monotonic()+.8
            while time.monotonic()<end:root.update();time.sleep(.02)
            root.update()
            capture(root,args.output/(names[args.step-1]+'.png'))
        finally:root.destroy()
        return
    args.work.mkdir(parents=True,exist_ok=False);args.output.mkdir(parents=True,exist_ok=True)
    progressive.run(project/'sample.csv',job);shutil.copytree(args.feedback_job,feedback)
    env=dict(os.environ);env['PYTHONPATH']=os.pathsep.join(sys.path)
    for step in range(1,10):
        subprocess.run([sys.executable,__file__,'--work',str(args.work),'--feedback-job',str(args.feedback_job),'--output',str(args.output),'--step',str(step)],env=env,check=True)
    manifest={'method':'Actual Tk application, fresh process per window, own-window device-context capture; no mockups or other desktop windows.',
              'sample':'Synthetic 13-record sample.csv','feedback':'DBLP-ACM benchmark label replay, not human participants',
              'images':[{'file':p.name,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in sorted(args.output.glob('*.png'))],
              'source_sha256':{name:hashlib.sha256((project/name).read_bytes()).hexdigest() for name in ['desktop.py','modern_ui.py','storage.py','twin_workflow.py','progressive.py','ai_model.py']}}
    (args.output/'manifest.json').write_text(json.dumps(manifest,indent=2));print(json.dumps(manifest,indent=2))

if __name__=='__main__':main()
