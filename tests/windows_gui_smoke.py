"""Run explicitly on Windows/Wine: verifies the GUI's Copy now command with native XCOPY."""
import json
import subprocess
from pathlib import Path
import sys
import tempfile
import tkinter as tk
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import app
from core import new_config
from automation import new_job,normalize_volume

with tempfile.TemporaryDirectory() as temporary:
    base=Path(temporary)
    source=base/'source';source.mkdir()
    (source/'example.txt').write_text('CopyJob integration',encoding='utf-8')
    (source/'nested').mkdir();(source/'nested'/'child.txt').write_text('nested content',encoding='utf-8')
    (source/'empty').mkdir()
    destination=base/'destination'
    config=new_config();job=new_job()
    job.update(source=str(source),destination=str(destination),name='GUI integration',enabled=True)
    volume_id=r'\\?\Volume{58081618-0000-0000-0000-100000000000}'+chr(92)
    job.update(trigger_volume=volume_id,source_volume=volume_id,destination_volume=volume_id)
    config['jobs']=[job]
    (base/'instance.json').write_text(json.dumps(config),encoding='utf-8')
    app.BASE=base
    # Wine lacks CIM inventory; inventory and the background-monitor spawn are stubbed.
    # Native XCOPY still performs the actual copy.
    app.win.inventory=lambda:{normalize_volume(volume_id):dict(DeviceID=volume_id,DriveLetter=source.drive,Label='Test',Disks=[dict(SerialNumber='TESTDISK',InterfaceType='USB')])}
    original_popen=subprocess.Popen
    monitor_requests=[]
    copy_phases=[]
    def popen(command,*args,**kwargs):
        if '--background' in command:
            monitor_requests.append(command)
            return None
        if command[0].lower()=='xcopy.exe':
            if '/T' in command:copy_phases.append('tree')
            else:
                assert (destination/source.name/'empty').is_dir() and (destination/source.name/'nested').is_dir(),'Directory phase must retain empty and nested folders before copying files'
                copy_phases.append('files')
        return original_popen(command,*args,**kwargs)
    subprocess.Popen=popen
    original=tk.Tk
    state={'done':False}
    def factory(*args,**kwargs):
        root=original(*args,**kwargs)
        def descendants(widget):
            yield widget
            for child in widget.winfo_children():yield from descendants(child)
        def invoke():
            serials=[w for w in descendants(root) if w.winfo_class()=='TCombobox' and 'TESTDISK' in w.cget('values')]
            interfaces=[w for w in descendants(root) if w.winfo_class()=='TCombobox' and 'USB' in w.cget('values')]
            assert len(serials)==3 and len(interfaces)==3,'Trigger, source and destination need populated hardware dropdowns'
            for box in serials:box.set('TESTDISK')
            for box in interfaces:box.set('USB')
            save_button=next(w for w in descendants(root) if w.winfo_class()=='TButton' and w.cget('text')=='Save job')
            save_button.invoke()
            button=next(w for w in descendants(root) if w.winfo_class()=='TButton' and w.cget('text')=='Copy now')
            button.invoke()
        def check():
            result=destination/source.name/'example.txt'
            state['done']=result.exists() and result.read_text(encoding='utf-8')=='CopyJob integration' and (result.parent/'nested'/'child.txt').read_text(encoding='utf-8')=='nested content' and (result.parent/'empty').is_dir()
            root.destroy()
        root.after(500,invoke);root.after(7000,check)
        return root
    tk.Tk=factory
    try:app.main()
    finally:subprocess.Popen=original_popen
    assert state['done'],'GUI did not produce expected copy'
    assert copy_phases==['tree','files'],'XCOPY must prepare directories before copying files'
    assert len(monitor_requests)==1,'Saving an enabled job must start monitoring once; manual copy must not start another monitor'
    print('PASS: full paths + selected volume -> GUI save normalization and monitor launch -> native XCOPY -> source folder, nested files and empty directory retained')
