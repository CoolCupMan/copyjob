"""Run explicitly on Windows/Wine: verifies the GUI's Copy now command with native XCOPY."""
import json
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
    destination=base/'destination'
    config=new_config();job=new_job()
    job.update(source=str(source),destination=str(destination),name='GUI integration')
    volume_id=r'\\?\Volume{58081618-0000-0000-0000-100000000000}'+chr(92)
    job.update(source_volume=volume_id,destination_volume=volume_id)
    config['jobs']=[job]
    (base/'instance.json').write_text(json.dumps(config),encoding='utf-8')
    app.BASE=base
    # Wine does not implement Windows' CIM inventory; only this inventory call is stubbed.
    app.win.inventory=lambda:{normalize_volume(volume_id):dict(DeviceID=volume_id,DriveLetter=source.drive,Label='Test')}
    original=tk.Tk
    state={'done':False}
    def factory(*args,**kwargs):
        root=original(*args,**kwargs)
        def descendants(widget):
            yield widget
            for child in widget.winfo_children():yield from descendants(child)
        def invoke():
            button=next(w for w in descendants(root) if w.winfo_class()=='TButton' and w.cget('text')=='Copy now')
            button.invoke()
        def check():
            result=destination/'example.txt'
            state['done']=result.exists() and result.read_text(encoding='utf-8')=='CopyJob integration'
            root.destroy()
        root.after(500,invoke);root.after(7000,check)
        return root
    tk.Tk=factory
    app.main()
    assert state['done'],'GUI did not produce expected copy'
    print('PASS: full paths + selected volume -> GUI save normalization -> native XCOPY -> expected file contents')
