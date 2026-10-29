"""Capture WMI volume events independently of inventory polling and long copies."""
import json
import os
import subprocess
import threading

EVENT_SCRIPT = r'''
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=[Text.UTF8Encoding]::new()
Register-WmiEvent -Class Win32_VolumeChangeEvent -SourceIdentifier CopyJobDriveEvents | Out-Null
[Console]::WriteLine('{"ready":true}')
try {
    while ($true) {
        $event=Wait-Event -SourceIdentifier CopyJobDriveEvents -Timeout 2
        if (!$event) { continue }
        $volume=$event.SourceEventArgs.NewEvent
        if ($volume.EventType -in @(2,3) -and $volume.DriveName) {
            [Console]::WriteLine((@{drive=[string]$volume.DriveName;type=[int]$volume.EventType} | ConvertTo-Json -Compress))
        }
        Remove-Event -EventIdentifier $event.EventIdentifier
    }
} finally { Unregister-Event -SourceIdentifier CopyJobDriveEvents -ErrorAction SilentlyContinue }
'''

class DriveEvents:
    def __init__(self,log):
        self.log=log;self.generations={};self.lock=threading.Lock()
        self.closed=threading.Event();self.process=None;self.thread=None
    def record(self,drive,event_type):
        if event_type not in (2,3) or not drive:return
        drive=drive.upper().rstrip('\\')
        with self.lock:self.generations[drive]=self.generations.get(drive,0)+1
        self.log(f'Drive event: {drive} '+('arrival' if event_type==2 else 'removal'))
    def generation(self,drive):
        with self.lock:return self.generations.get(drive.upper(),0)
    def start(self):
        if os.name!='nt':return
        def worker():
            last_error=None
            while not self.closed.is_set():
                try:
                    with subprocess.Popen(['powershell.exe','-NoLogo','-NoProfile','-NonInteractive','-Command',EVENT_SCRIPT],
                            creationflags=0x08000000,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
                            encoding='utf-8',errors='replace',bufsize=1) as process:
                        self.process=process
                        if self.closed.is_set():process.terminate()
                        errors=[]
                        for line in process.stdout:
                            if self.closed.is_set():break
                            try:data=json.loads(line)
                            except ValueError:
                                if line.strip():errors=(errors+[line.strip()])[-5:]
                                continue
                            if data.get('ready'):self.log('Live WMI drive-event listener ready.')
                            else:self.record(data.get('drive'),data.get('type'))
                        if process.poll() is None:process.terminate()
                        process.wait(timeout=5)
                    if not self.closed.is_set():raise RuntimeError('WMI event listener exited; polling remains active. '+' '.join(errors)[-1000:])
                except Exception as exc:
                    if str(exc)!=last_error and not self.closed.is_set():self.log('Drive events: '+str(exc));last_error=str(exc)
                self.closed.wait(15)
        self.thread=threading.Thread(target=worker,daemon=True);self.thread.start()
    def close(self):
        self.closed.set()
        if self.process and self.process.poll() is None:
            try:self.process.terminate()
            except OSError:pass
        if self.thread:self.thread.join(timeout=2)
