"""Windows WMI inventory, explicit scheduled startup, and native copy execution."""
import json
import os
from pathlib import Path
import subprocess
import threading
import time
from automation import normalize_volume,prepare_job,xcopy_flags,Scheduler,trigger_signature
from core import copy_job,validate

NO_WINDOW=0x08000000 if os.name=='nt' else 0

def powershell(script,timeout=30):
    result=subprocess.run(['powershell.exe','-NoLogo','-NoProfile','-NonInteractive','-Command',script],
        creationflags=NO_WINDOW,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
        encoding='utf-8',errors='replace',timeout=timeout)
    if result.returncode:raise RuntimeError(result.stderr.strip() or 'PowerShell failed')
    return result.stdout

def psquote(value):return "'"+str(value).replace("'","''")+"'"

def inventory():
    text=powershell("[Console]::OutputEncoding=[Text.UTF8Encoding]::new(); @("+
        "Get-CimInstance Win32_Volume | Select-Object DeviceID,DriveLetter,Label,DriveType,FileSystem,BootVolume,SystemVolume"+
        ") | ConvertTo-Json -Compress")
    rows=json.loads(text or '[]')
    if isinstance(rows,dict):rows=[rows]
    return {normalize_volume(row['DeviceID']):row for row in rows}

def assign_letter(volume_id,letter):
    normalize_volume(volume_id)
    letter=letter.strip().upper().rstrip(':')
    if len(letter)!=1 or letter not in 'DEFGHIJKLMNOPQRSTUVWXYZ':raise ValueError('Choose D through Z.')
    # Explicit UAC elevation, no automatic reassignment or occupied-letter takeover.
    script=("$ErrorActionPreference='Stop'; $v=Get-CimInstance Win32_Volume | Where-Object DeviceID -EQ "+psquote(volume_id)+
        "; if(!$v){throw 'Volume unavailable'}; if($v.BootVolume -or $v.SystemVolume){throw 'System volume cannot be reassigned'}; "+
        "$occupied=Get-CimInstance Win32_Volume | Where-Object DriveLetter -EQ "+psquote(letter+':')+
        "; if($occupied -and $occupied.DeviceID -ne $v.DeviceID){throw 'Drive letter occupied'}; "+
        "Set-CimInstance -InputObject $v -Property @{DriveLetter="+psquote(letter+':')+"} | Out-Null")
    import base64
    encoded=base64.b64encode(script.encode('utf-16le')).decode()
    wrapper="$p=Start-Process powershell.exe -Verb RunAs -Wait -PassThru -ArgumentList "+psquote('-NoProfile -NonInteractive -EncodedCommand '+encoded)+"; if($p.ExitCode -ne 0){throw 'Assignment failed; volume or drive letter may be unavailable.'}"
    powershell(wrapper,120)

def task_name(config):return 'CopyJob-'+config['instance_id']

def register_task(exe,config,remove=False):
    name=task_name(config)
    if remove:
        return powershell("Stop-ScheduledTask -TaskName "+psquote(name)+" -ErrorAction SilentlyContinue; Unregister-ScheduledTask -TaskName "+psquote(name)+" -Confirm:$false -ErrorAction Stop")
    script=("$ErrorActionPreference='Stop'; $u=[Security.Principal.WindowsIdentity]::GetCurrent().Name; "+
        "$a=New-ScheduledTaskAction -Execute "+psquote(exe)+" -Argument '--background'; "+
        "$t=New-ScheduledTaskTrigger -AtLogOn -User $u; "+
        "$p=New-ScheduledTaskPrincipal -UserId $u -LogonType Interactive -RunLevel Limited; "+
        "$s=New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1); "+
        "Register-ScheduledTask -TaskName "+psquote(name)+" -Action $a -Trigger $t -Principal $p -Settings $s -Force | Out-Null; "+
        "Start-ScheduledTask -TaskName "+psquote(name))
    return powershell(script)

def _run_job(job,volumes,log,cancelled):
    source,destination=prepare_job(job,volumes)
    log(job['name']+': source = '+source)
    log(job['name']+': destination = '+destination)
    validate(source,destination)
    if job.get('engine','xcopy')=='builtin':
        count=copy_job(source,destination,log,cancelled)
        log(f'{job["name"]}: {count} file(s) copied')
        return True
    engine=job.get('engine','xcopy')
    environment=os.environ.copy()
    if engine=='powershell':
        script=Path(job.get('script_path',''))
        if not script.is_absolute() or script.suffix.lower()!='.ps1' or not script.is_file():
            raise ValueError('Choose an existing absolute .ps1 script path.')
        command=['powershell.exe','-NoLogo','-NoProfile','-NonInteractive','-File',str(script)]
        environment.update(COPYJOB_SOURCE=source,COPYJOB_DESTINATION=destination,COPYJOB_JOB_ID=job['id'])
        log(job['name']+': starting selected PowerShell script (existing execution policy applies).')
    elif engine=='xcopy':
        flags=xcopy_flags(job)
        Path(destination).mkdir(parents=True,exist_ok=True)
        command=['xcopy.exe',source,destination.rstrip('\\')+'\\',*flags]
        log(f'{job["name"]}: XCOPY '+ ' '.join(flags))
    else:raise ValueError('Unsupported job engine: '+engine)
    with subprocess.Popen(command,env=environment,creationflags=NO_WINDOW,stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,errors='replace') as process:
        def stop_when_cancelled():
            while process.poll() is None:
                if cancelled.wait(.25):
                    if process.poll() is None:process.terminate()
                    return
        threading.Thread(target=stop_when_cancelled,daemon=True).start()
        for line in process.stdout:log(line.rstrip())
        code=process.wait()
    if cancelled.is_set():raise InterruptedError('Copy cancelled; completed files are retained.')
    if engine=='powershell':
        log(f'{job["name"]}: PowerShell exit {code}')
        return code==0
    meanings={0:'Files copied',1:'No matching files',2:'Cancelled',4:'Initialization or syntax error',5:'Disk write error'}
    log(f'{job["name"]}: XCOPY exit {code} — {meanings.get(code,"Unexpected result")}')
    return code in (0,1)

def run_job(job,volumes,log,cancelled):
    if os.name!='nt':return _run_job(job,volumes,log,cancelled)
    import ctypes
    from ctypes import wintypes
    import uuid
    identity=str(uuid.UUID(job['id']))
    kernel=ctypes.windll.kernel32
    kernel.CreateMutexW.argtypes=[ctypes.c_void_p,wintypes.BOOL,wintypes.LPCWSTR]
    kernel.CreateMutexW.restype=wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes=[wintypes.HANDLE,wintypes.DWORD]
    kernel.ReleaseMutex.argtypes=[wintypes.HANDLE]
    kernel.CloseHandle.argtypes=[wintypes.HANDLE]
    handle=kernel.CreateMutexW(None,False,'Global\\CopyJob-job-'+identity)
    if not handle:raise ctypes.WinError()
    acquired=False
    try:
        result=kernel.WaitForSingleObject(handle,0)
        if result==258:
            log(job['name']+': already running in another CopyJob process; retry later.')
            return False
        if result not in (0,128):raise ctypes.WinError()
        acquired=True
        return _run_job(job,volumes,log,cancelled)
    finally:
        if acquired:kernel.ReleaseMutex(handle)
        kernel.CloseHandle(handle)

def watch(base,stop,log):
    scheduler=Scheduler()
    last_error=None
    job_errors={}
    while not stop.is_set():
        try:
            config=json.loads((base/'instance.json').read_text(encoding='utf-8'))
            if (base/'pause-background').exists():
                stop.wait(3);continue
            volumes=inventory()
            for job in config.get('jobs',[]):
                if stop.is_set():break
                if not job.get('enabled'):
                    scheduler.states.pop(job['id'],None);continue
                try:
                    signature=trigger_signature(job,volumes,lambda root:Path(root).is_dir())
                except Exception as exc:
                    if job_errors.get(job['id'])!=str(exc):log(job['name']+': '+str(exc))
                    job_errors[job['id']]=str(exc)
                    continue
                if scheduler.due(job,signature):
                    try:success=run_job(job,volumes,log,stop)
                    except Exception as exc:log(job['name']+': '+str(exc));success=False
                    scheduler.finish(job,success)
            last_error=None
        except Exception as exc:
            if str(exc)!=last_error:log('Monitor: '+str(exc));last_error=str(exc)
        stop.wait(3)
