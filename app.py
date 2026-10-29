"""CopyJob desktop settings and explicit per-user background monitor."""
import json
import os
from pathlib import Path
import queue
import shutil
import sys
import threading
import tkinter as tk
from tkinter import filedialog,messagebox,ttk
from datetime import datetime
from core import APP_ID,VERSION,new_config
from automation import FLAGS,new_job,normalize_volume,xcopy_flags,volume_folder,clean_folder
import windows_runtime as win

BASE=Path(sys.executable).parent if getattr(sys,'frozen',False) else Path(__file__).parent

def load():
    path=BASE/'instance.json'
    config=json.loads(path.read_text(encoding='utf-8')) if path.exists() else new_config()
    if 'jobs' not in config:
        config['jobs']=[]
        if config.get('source') and config.get('destination'):
            job=new_job();job.update(source=config['source'],destination=config['destination'],name='Imported 1.0 job',engine='builtin')
            config['jobs'].append(job)
    import uuid
    uuid.UUID(config['instance_id'])
    config.update(version=VERSION,schema=2)
    return config

def save(config):
    path=BASE/'instance.tmp'
    path.write_text(json.dumps(config,indent=2),encoding='utf-8')
    path.replace(BASE/'instance.json')

def background():
    config=load()
    def log(message):
        with (BASE/'copyjob.log').open('a',encoding='utf-8') as output:
            output.write(datetime.now().isoformat(timespec='seconds')+' '+message+'\n')
    import ctypes
    from ctypes import wintypes
    kernel=ctypes.windll.kernel32
    kernel.CreateMutexW.argtypes=[ctypes.c_void_p,wintypes.BOOL,wintypes.LPCWSTR]
    kernel.CreateMutexW.restype=wintypes.HANDLE
    handle=kernel.CreateMutexW(None,False,'Global\\CopyJob-monitor-'+config['instance_id'])
    if not handle:raise ctypes.WinError()
    if kernel.GetLastError()==183:
        log('CopyJob '+VERSION+': another monitor is already running. If updating, Stop monitoring, wait for Background monitor stopped, then Start monitoring to use the new executable.')
        kernel.CloseHandle.argtypes=[wintypes.HANDLE];kernel.CloseHandle(handle);return
    log('Background monitor started: CopyJob '+VERSION+'; PID '+str(os.getpid()))
    try:win.watch(BASE,threading.Event(),log)
    finally:
        kernel.CloseHandle.argtypes=[wintypes.HANDLE];kernel.CloseHandle(handle)

def main():
    config=load();save(config)
    root=tk.Tk();root.title(f'CopyJob {VERSION} — {config["instance_id"][:8]}');root.geometry('1250x960')
    events=queue.Queue();cancelled=threading.Event();busy=False;closing=False
    log_path=BASE/'copyjob.log'
    log_offset=max(0,log_path.stat().st_size-65536) if log_path.exists() else 0
    volumes={};options={'Fixed path / no volume ID':''};selected=None
    frame=ttk.Frame(root,padding=12);frame.pack(fill='both',expand=True)
    ttk.Label(frame,text=f'CopyJob {VERSION} | Instance {config["instance_id"]}').pack(anchor='w')
    ttk.Label(frame,text='Background setup is explicit. Jobs run after sign-in and reconnect, including drive-letter changes.').pack(anchor='w')
    bar=ttk.Frame(frame);bar.pack(fill='x',pady=4)
    jobs=tk.Listbox(frame,height=4,exportselection=False);jobs.pack(fill='x')
    vars={key:tk.StringVar() for key in ['name','source','destination','trigger_volume','source_volume','destination_volume','engine','delay','retry_seconds','extra_flags','script_path','preferred_letter','trigger_serial','trigger_interface','source_serial','source_interface','destination_serial','destination_interface','layout']}
    enabled=tk.BooleanVar();flagvars={flag:tk.BooleanVar() for flag in FLAGS}
    vars['engine'].set('xcopy');vars['delay'].set('3');vars['retry_seconds'].set('60')
    controls=ttk.Frame(frame);controls.pack(fill='x')
    volume_boxes=[]
    hardware_boxes={}
    layouts={'Source folder and contents':'folder','Contents only':'contents','Full source path':'full_path'}
    for row,(label,key) in enumerate([('Job name','name'),('Trigger volume','trigger_volume'),('Trigger disk serial','trigger_serial'),('Source volume','source_volume'),('Source disk serial','source_serial'),('Source folder','source'),('Destination volume','destination_volume'),('Target disk serial','destination_serial'),('Destination folder','destination'),('Optional PS1 script','script_path'),('Preferred trigger letter','preferred_letter')]):
        ttk.Label(controls,text=label,width=20).grid(row=row,column=0,sticky='w',pady=2)
        if key.endswith('volume'):
            widget=ttk.Combobox(controls,textvariable=vars[key],width=95,values=list(options));volume_boxes.append(widget)
        elif key.endswith('_serial'):
            role=key.split('_')[0]
            widget=ttk.Frame(controls)
            serial_box=ttk.Combobox(widget,textvariable=vars[key],values=[''],width=35)
            serial_box.pack(side='left',fill='x',expand=True)
            ttk.Label(widget,text=' Interface (optional) ').pack(side='left')
            interface_box=ttk.Combobox(widget,textvariable=vars[role+'_interface'],values=[''],width=16)
            interface_box.pack(side='left')
            ttk.Button(widget,text='Read selected disk',command=lambda r=role:selected_disk(r)).pack(side='left',padx=3)
            hardware_boxes[role]=(serial_box,interface_box)
        else:widget=ttk.Entry(controls,textvariable=vars[key],width=95)
        widget.grid(row=row,column=1,sticky='ew')
        if key.endswith('_volume'):widget.bind('<<ComboboxSelected>>',lambda _:update_hardware_choices())
        if key in ('source','destination'):
            def browse_folder(k=key):
                chosen=filedialog.askdirectory()
                if chosen:vars[k].set(chosen)
            ttk.Button(controls,text='Browse…',command=browse_folder).grid(row=row,column=2,padx=3)
    controls.columnconfigure(1,weight=1)
    ttk.Label(frame,text='Selected volume controls the drive: E:\\Backup becomes Backup and follows that volume. Without a volume ID, the full path stays fixed.').pack(anchor='w')
    layout_row=ttk.Frame(frame);layout_row.pack(fill='x',pady=3)
    ttk.Label(layout_row,text='Folder layout: ').pack(side='left')
    ttk.Combobox(layout_row,textvariable=vars['layout'],values=list(layouts),state='readonly',width=28).pack(side='left')
    ttk.Label(layout_row,text=' Destination is the parent folder; Preview paths shows the final location.').pack(side='left')
    settings=ttk.Frame(frame);settings.pack(fill='x',pady=5)
    ttk.Checkbutton(settings,text='Enable automatic job',variable=enabled).pack(side='left')
    ttk.Combobox(settings,textvariable=vars['engine'],values=['xcopy','builtin','powershell'],state='readonly',width=9).pack(side='left',padx=6)
    for label,key in [('Delay seconds','delay'),('Retry seconds','retry_seconds')]:
        ttk.Label(settings,text=label).pack(side='left');ttk.Entry(settings,textvariable=vars[key],width=6).pack(side='left',padx=4)
    flags=ttk.LabelFrame(frame,text='XCOPY switches (native Windows version; /W and /-Y are interactive-only)');flags.pack(fill='x')
    for i,flag in enumerate(FLAGS):ttk.Checkbutton(flags,text='/'+flag,variable=flagvars[flag]).grid(row=i//16,column=i%16,sticky='w')
    row=ttk.Frame(frame);row.pack(fill='x',pady=3)
    ttk.Label(row,text='Additional switches, e.g. /D:10-29-2026 /EXCLUDE:C:\\exclude.txt').pack(side='left')
    ttk.Entry(row,textvariable=vars['extra_flags']).pack(side='left',fill='x',expand=True)
    ttk.Label(frame,text='XCOPY may overwrite older or newer files depending on flags. /L previews. No deletion/mirroring is performed.').pack(anchor='w')
    actions=ttk.Frame(frame);actions.pack(fill='x',pady=4)
    backgroundbar=ttk.Frame(frame);backgroundbar.pack(fill='x',pady=4)
    status=tk.StringVar(value='Ready. Save settings before enabling background startup.')
    ttk.Label(frame,textvariable=status,wraplength=1050).pack(anchor='w')
    output=tk.Text(frame,height=10,state='disabled');output.pack(fill='both',expand=True)

    def log(text):events.put(('log',text))
    def error(exc):messagebox.showerror('CopyJob',str(exc))
    def names():
        jobs.delete(0,'end')
        for job in config['jobs']:jobs.insert('end',('✓ ' if job['enabled'] else '○ ')+job['name'])
    def show_job(index):
        nonlocal selected
        if index is None:return
        selected=index;job=config['jobs'][index]
        for key,var in vars.items():
            value=job.get(key,'')
            if key.endswith('volume'):
                value=next((text for text,id in options.items() if id.casefold()==value.casefold()),value)
            if key=='layout':value=next((label for label,mode in layouts.items() if mode==job.get('layout','folder')),'Source folder and contents')
            var.set(str(value))
        enabled.set(job['enabled'])
        for flag,var in flagvars.items():var.set(flag in job.get('flags',[]))
        update_hardware_choices()
    jobs.bind('<<ListboxSelect>>',lambda _:show_job(jobs.curselection()[0]) if jobs.curselection() else None)
    def add():
        config['jobs'].append(new_job());names();jobs.selection_set(len(config['jobs'])-1);show_job(len(config['jobs'])-1)
    def remove():
        nonlocal selected
        if selected is not None and messagebox.askyesno('Delete job','Remove this job configuration?'):
            config['jobs'].pop(selected);selected=None;save(config);names()
    def start_monitor():
        try:
            import subprocess
            (BASE/'stop-background').unlink(missing_ok=True)
            command=[sys.executable,'--background'] if getattr(sys,'frozen',False) else [sys.executable,str(Path(__file__).resolve()),'--background']
            subprocess.Popen(command,creationflags=win.NO_WINDOW,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            log('Background monitor requested. Enable login startup to restore monitoring after reboot.')
        except Exception as exc:error(exc)
    def stop_monitor():
        (BASE/'stop-background').touch()
        log('Monitor stop requested; an active copy finishes first. Start monitoring or save an enabled job to resume.')
    def update_hardware_choices():
        for role,(serial_box,interface_box) in hardware_boxes.items():
            selected_volume=options.get(vars[role+'_volume'].get(),vars[role+'_volume'].get())
            volume=volumes.get(selected_volume.casefold(),{})
            disks=volume.get('Disks') or []
            if isinstance(disks,dict):disks=[disks]
            serial_box['values']=['',*sorted({str(d.get('SerialNumber') or '').strip() for d in disks}-{''})]
            interface_box['values']=['',*sorted({str(d.get('InterfaceType') or '').strip() for d in disks}-{''})]
    def selected_disk(role='trigger'):
        value=options.get(vars[role+'_volume'].get(),vars[role+'_volume'].get())
        try:
            volume=volumes.get(normalize_volume(value))
            if not volume:raise ValueError('Select a connected '+role+' volume and refresh first.')
            disks=volume.get('Disks') or []
            if isinstance(disks,dict):disks=[disks]
            vars[role+'_serial'].set('');vars[role+'_interface'].set('')
            if len(disks)!=1:
                log(role+': no single physical disk identity; using Volume-ID only.')
                return
            serial=str(disks[0].get('SerialNumber') or '').strip()
            interface=str(disks[0].get('InterfaceType') or '').strip()
            vars[role+'_serial'].set(serial);vars[role+'_interface'].set(interface)
            log(role+': '+str(disks[0].get('Model') or '')+'; serial '+(serial or 'not reported — using Volume-ID')+'; interface '+(interface or 'any'))
        except Exception as exc:error(exc)
    def store(start_automatic=True):
        if selected is None:raise ValueError('Add or select a job first.')
        job=dict(config['jobs'][selected])
        for key,var in vars.items():
            value=var.get().strip()
            if key.endswith('volume'):value=options.get(value,value);normalize_volume(value)
            if key=='layout':value=layouts.get(value,value)
            job[key]=value
        for key in ['delay','retry_seconds']:
            job[key]=float(job[key])
            if not 0<=job[key]<=86400:raise ValueError('Timing must be between 0 and 86400 seconds.')
        job.update(enabled=enabled.get(),flags=[f for f,v in flagvars.items() if v.get()])
        if not job['source'] or not job['destination']:raise ValueError('Enter source and destination folders.')
        for key in ('source','destination'):
            job[key]=volume_folder(job[key]) if job.get(key+'_volume') else clean_folder(job[key])
            vars[key].set(job[key])
        for role in ('trigger','source','destination'):
            if (job.get(role+'_serial') or job.get(role+'_interface')) and not job.get(role+'_volume'):raise ValueError('Choose a '+role+' Volume-ID when setting hardware filters.')
        job['preferred_letter']=job.get('preferred_letter','').upper().rstrip(':')
        if job['preferred_letter'] and (job['preferred_letter'] not in 'DEFGHIJKLMNOPQRSTUVWXYZ' or len(job['preferred_letter'])!=1 or not job['trigger_volume']):raise ValueError('Preferred letter needs a trigger volume ID and one letter D–Z.')
        if job['engine']=='xcopy':xcopy_flags(job)
        config['jobs'][selected]=job;save(config);names();jobs.selection_set(selected)
        status.set('Saved. Background monitor reloads these settings automatically.')
        if job['enabled'] and start_automatic:start_monitor()
        return job
    def preview():
        draft=dict(config['jobs'][selected]) if selected is not None else {}
        for key in ('trigger_volume','source_volume','destination_volume','source','destination','trigger_serial','trigger_interface','source_serial','source_interface','destination_serial','destination_interface','layout'):
            value=vars[key].get().strip()
            draft[key]=options.get(value,value) if key.endswith('volume') else layouts.get(value,value) if key=='layout' else value
        def worker():
            try:
                source,destination=win.prepare_job(draft,win.inventory())
                log('Preview source: '+source)
                log('Preview destination: '+destination)
                log('Source folder exists: '+str(Path(source).is_dir()))
            except Exception as exc:log('Preview: '+str(exc))
        threading.Thread(target=worker,daemon=True).start()
    def safe_store():
        try:store()
        except Exception as exc:error(exc)
    def refresh():
        def worker():
            try:events.put(('volumes',win.inventory()))
            except Exception as exc:log('Volume inventory failed: '+str(exc))
        threading.Thread(target=worker,daemon=True).start()
    def run():
        nonlocal busy
        if busy:return
        try:job=store(False)
        except Exception as exc:error(exc);return
        busy=True;cancelled.clear();status.set('Copying…')
        def worker():
            try:
                ok=win.run_job(job,win.inventory(),log,cancelled)
                log('Job complete.' if ok else 'Job failed; see native XCOPY output above.')
            except Exception as exc:log('Copy failed: '+str(exc))
            finally:events.put(('done',None))
        threading.Thread(target=worker,daemon=False).start()
    def startup(remove=False):
        if remove:(BASE/'stop-background').touch()
        else:(BASE/'stop-background').unlink(missing_ok=True)
        if not getattr(sys,'frozen',False):error('Use the packaged Windows EXE for startup registration.');return
        def worker():
            try:win.register_task(sys.executable,config,remove);log('Startup removed.' if remove else 'Startup enabled; monitor started.')
            except Exception as exc:log('Task setup failed: '+str(exc))
        threading.Thread(target=worker,daemon=True).start()
    def pause():
        path=BASE/'pause-background'
        if path.exists():path.unlink();status.set('Automatic jobs resumed.')
        else:path.touch();status.set('Automatic jobs paused; a current copy finishes. Manual copy remains available.')
    def assign():
        value=options.get(vars['trigger_volume'].get(),vars['trigger_volume'].get())
        from tkinter.simpledialog import askstring
        letter=askstring('Assign drive letter','Preferred letter D–Z for the selected trigger volume. Requires UAC approval; occupied letters are preserved.')
        if not letter:return
        def worker():
            try:win.assign_letter(value,letter);log('Drive letter assigned.');refresh()
            except Exception as exc:log('Assignment failed: '+str(exc))
        threading.Thread(target=worker,daemon=True).start()
    def export_wmi():
        path=filedialog.asksaveasfilename(defaultextension='.ps1',initialfile='CopyJob-WMI-Setup.ps1')
        if not path:return
        template=(Path(getattr(sys,'_MEIPASS',BASE))/'wmi_setup.ps1').read_text(encoding='utf-8')
        import base64
        assignments={}
        letters={}
        try:
            for job in config['jobs']:
                letter=job.get('preferred_letter','')
                if not letter:continue
                volume=normalize_volume(job['trigger_volume'])
                if not volume or len(letter)!=1 or letter not in 'DEFGHIJKLMNOPQRSTUVWXYZ':raise ValueError('Invalid preferred letter mapping.')
                if letter in letters and letters[letter]!=volume:raise ValueError('Two volumes request the same letter.')
                binding=dict(volume=volume,letter=letter+':',serial=job.get('trigger_serial','').strip(),interface=job.get('trigger_interface','').strip())
                if volume in assignments and assignments[volume]!=binding:raise ValueError('One volume has conflicting letter or hardware mappings.')
                assignments[volume]=binding;letters[letter]=volume
            data=list(assignments.values())
            encoded=base64.b64encode(json.dumps(data).encode('utf-8')).decode()
            script=template.replace('__TASK_NAME__',win.task_name(config)).replace('__ASSIGNMENTS_JSON_B64__',encoded)
            Path(path).write_text(script,encoding='utf-8-sig')
        except Exception as exc:error(exc);return
        messagebox.showinfo('WMI setup exported','First enable login startup. Then run this script as administrator to add the optional permanent WMI consumer. Use -Remove to remove only this instance’s consumer. The consumer starts the configured user task after sign-in. Saved preferred letters optionally add a SYSTEM startup task that assigns only those volumes and never takes occupied letters.')
    def help_flags():
        def worker():
            try:
                import subprocess
                result=subprocess.run(['xcopy.exe','/?'],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,creationflags=win.NO_WINDOW,text=True,errors='replace',timeout=10)
                log(result.stdout)
            except Exception as exc:log(str(exc))
        threading.Thread(target=worker,daemon=True).start()
    def install():
        if not getattr(sys,'frozen',False):error('Build the Windows EXE first.');return
        parent=filedialog.askdirectory(title='Parent folder for independent installation')
        if not parent:return
        identity=new_config();identity.update(schema=2,jobs=[])
        target=Path(parent)/f'CopyJob-{VERSION}-{identity["instance_id"]}'
        try:
            target.mkdir();shutil.copy2(sys.executable,target/'CopyJob.exe')
            (target/'instance.json').write_text(json.dumps(identity,indent=2),encoding='utf-8')
            messagebox.showinfo('Installed',f'Run {target / "CopyJob.exe"}. This instance has separate jobs, UUID and startup settings.')
        except Exception as exc:error(exc)
    for text,command in [('Add job',add),('Delete job',remove),('Refresh volumes',refresh),('Use selected disk ID',lambda:selected_disk('trigger')),('Assign trigger letter…',assign),('Install independent instance…',install)]:ttk.Button(bar,text=text,command=command).pack(side='left',padx=2)
    for text,command in [('Save job',safe_store),('Preview paths',preview),('Copy now',run),('Cancel manual copy',cancelled.set),('Show installed XCOPY options',help_flags)]:ttk.Button(actions,text=text,command=command).pack(side='left',padx=2)
    for text,command in [('Start monitoring',start_monitor),('Stop monitoring',stop_monitor),('Enable login startup',startup),('Remove login startup',lambda:startup(True)),('Pause / resume background',pause),('Export WMI setup…',export_wmi)]:ttk.Button(backgroundbar,text=text,command=command).pack(side='left',padx=2)
    def tick():
        nonlocal volumes,options,busy,log_offset
        while True:
            try:kind,data=events.get_nowait()
            except queue.Empty:break
            if kind=='volumes':
                volumes=data;options={'Fixed path / no volume ID':''}
                for id,v in volumes.items():options[f'{v.get("DriveLetter") or "No letter"} | {v.get("Label") or "Unlabelled"} | {v["DeviceID"]}']=v['DeviceID']
                for box in volume_boxes:box['values']=list(options)
                if selected is not None:show_job(selected)
                log(f'{len(volumes)} Windows volumes found (internal, USB and external).')
            elif kind=='done':busy=False;status.set('Idle — see log for result.')
            elif kind=='log':
                line=datetime.now().isoformat(timespec='seconds')+' '+data+'\n'
                try:
                    with (BASE/'copyjob.log').open('a',encoding='utf-8') as handle:handle.write(line)
                except OSError:status.set('Cannot write log beside EXE.')
        try:
            path=BASE/'copyjob.log'
            if path.exists():
                if path.stat().st_size<log_offset:log_offset=0
                with path.open('rb') as handle:
                    handle.seek(log_offset)
                    data=handle.read()
                    log_offset=handle.tell()
                if data:
                    output.configure(state='normal');output.insert('end',data.decode('utf-8',errors='replace'));output.see('end');output.configure(state='disabled')
        except OSError:pass
        if closing and not busy:root.destroy();return
        root.after(200,tick)
    def close():
        nonlocal closing
        closing=True;cancelled.set();status.set('Closing settings; registered background automation continues.')
    root.protocol('WM_DELETE_WINDOW',close)
    names()
    if config['jobs']:jobs.selection_set(0);show_job(0)
    else:add()
    refresh();root.after(100,tick);root.mainloop()

if __name__=='__main__':
    try:
        if '--background' in sys.argv:background()
        else:main()
    except Exception as exc:
        if '--background' in sys.argv:
            with (BASE/'copyjob.log').open('a',encoding='utf-8') as output:output.write('Background failure: '+str(exc)+'\n')
            raise SystemExit(1)
        messagebox.showerror('CopyJob startup failed',str(exc))
