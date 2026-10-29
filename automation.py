"""Volume-aware job configuration and reconnect scheduling (testable without Windows)."""
import ntpath
import re
import time
import uuid

VOLUME = re.compile(r'^\\\\\?\\Volume\{[0-9a-fA-F-]{36}\}\\$')
# Native XCOPY remains responsible for OS-specific combinations and filesystem capabilities.
FLAGS = ['A','M','D','S','E','V','W','C','I','Q','F','L','G','H','R','T','U','K','N','O','X','Y','-Y','Z','B','J','COMPRESS','SPARSE','NOCLONE']

def new_job():
    return dict(id=str(uuid.uuid4()), name='New copy job', enabled=False,
                trigger_volume='', trigger_serial='', trigger_interface='', source_volume='', destination_volume='', source='',
                destination='', engine='xcopy', flags=['E','I','H','K','Y'],
                extra_flags='', script_path='', preferred_letter='', delay=3, retry_seconds=60)

def normalize_volume(value):
    value=value.strip()
    if value and not VOLUME.fullmatch(value):
        raise ValueError('Expected a volume GUID, e.g. \\\\?\\Volume{...}\\')
    return value.casefold()

def clean_folder(value):
    value=value.strip()
    if len(value)>=2 and value[0]==value[-1] and value[0] in ('"', "'"):
        value=value[1:-1].strip()
    if not value:raise ValueError('Enter a folder path; use . for the selected volume root.')
    return value.replace('/','\\')

def volume_folder(value):
    """A selected volume identifies the disk; retain only a pasted drive path's folder."""
    value=clean_folder(value)
    drive,tail=ntpath.splitdrive(value)
    if drive:
        if not re.fullmatch(r'[A-Za-z]:',drive) or not tail.startswith('\\'):
            raise ValueError('With a volume selected, use a relative folder or a full drive path such as E:\\Backup; UNC/device paths are not supported here.')
        value=tail.lstrip('\\') or '.'
    elif value.startswith('\\'):
        value=value.lstrip('\\') or '.'
    if '..' in [part.rstrip(' ') for part in value.split('\\')] or ':' in value:
        raise ValueError('A volume folder cannot contain .. or a drive-relative path.')
    return ntpath.normpath(value)

def resolve_path(path, volume_id, volumes):
    if not volume_id:
        path=clean_folder(path)
        drive,tail=ntpath.splitdrive(path)
        if not drive or not ntpath.isabs(path):
            raise ValueError('Without a volume ID, use a full path such as C:\\Users\\Name\\Documents.')
        return path
    volume=volumes.get(normalize_volume(volume_id))
    if not volume or not volume.get('DriveLetter'):
        raise FileNotFoundError('Waiting for the selected volume to receive a drive letter: '+volume_id)
    relative=volume_folder(path)
    return ntpath.normpath(ntpath.join(volume['DriveLetter']+'\\',relative))

def xcopy_flags(job):
    tokens=['/'+f.upper().lstrip('/') for f in job.get('flags',[])]
    text=job.get('extra_flags','').strip()
    pattern=re.compile(r'/[-A-Za-z]+(?::(?:"[^"\r\n]*"|[^\s"]+))?')
    position=0
    for match in pattern.finditer(text):
        if text[position:match.start()].strip():raise ValueError('Invalid XCOPY switches.')
        tokens.append(match.group().replace('"',''))
        position=match.end()
    if text[position:].strip():raise ValueError('Invalid XCOPY switches.')
    allowed=set(FLAGS)
    for token in tokens:
        if not re.fullmatch(r'/[-A-Za-z]+(?::[^\r\n"]+)?', token):
            raise ValueError('XCOPY options must be individual switches, not commands or paths.')
        flag=token[1:].split(':',1)[0].upper()
        if flag not in allowed and flag not in {'EXCLUDE'}:
            raise ValueError('Unknown XCOPY option: '+token)
    # Background jobs must never wait indefinitely for interactive prompts.
    if any(t.upper() in {'/W','/-Y'} for t in tokens):
        raise ValueError('/W and /-Y require interaction; use manual console XCOPY for these modes.')
    if not any(t.upper()=='/Y' for t in tokens):tokens.append('/Y')
    if not any(t.upper()=='/I' for t in tokens):tokens.append('/I')
    return tokens

def prepare_job(job,volumes):
    trigger=normalize_volume(job.get('trigger_volume',''))
    if trigger and (trigger not in volumes or not volumes[trigger].get('DriveLetter')):
        raise FileNotFoundError('Waiting for trigger volume / drive letter.')
    if (job.get('trigger_serial') or job.get('trigger_interface')) and not trigger_signature(job,volumes,lambda _:True):
        raise FileNotFoundError('Trigger volume is absent or disk serial/interface does not match.')
    source=resolve_path(job['source'],job.get('source_volume',''),volumes)
    destination=resolve_path(job['destination'],job.get('destination_volume',''),volumes)
    a,b=ntpath.normcase(ntpath.normpath(source)),ntpath.normcase(ntpath.normpath(destination))
    try: common=ntpath.commonpath([a,b])
    except ValueError:common=None
    if common in (a,b):raise ValueError('Source and destination must be separate non-nested folders.')
    return source,destination

def disk_matches(job,volume):
    serial=job.get('trigger_serial','').strip().casefold()
    interface=job.get('trigger_interface','').strip().casefold()
    if not serial and not interface:return True
    disks=volume.get('Disks') or []
    if isinstance(disks,dict):disks=[disks]
    return any((not serial or str(d.get('SerialNumber') or '').strip().casefold()==serial)
               and (not interface or str(d.get('InterfaceType') or '').strip().casefold()==interface)
               for d in disks)

def trigger_signature(job,volumes,root_available):
    """Only drive identity/letter determines a new automatic trigger."""
    identity=normalize_volume(job.get('trigger_volume','') or job.get('destination_volume',''))
    if identity:
        volume=volumes.get(identity)
        letter=volume.get('DriveLetter') if volume else None
        return (identity,letter.upper()) if letter and disk_matches(job,volume) else None
    if job.get('trigger_serial','').strip() or job.get('trigger_interface','').strip():
        raise ValueError('Select a trigger Volume-ID when using disk-serial or interface filters.')
    # Legacy fixed-path jobs follow destination drive availability, not its folder.
    path=clean_folder(job['destination'])
    drive,_=ntpath.splitdrive(path)
    if not drive or not ntpath.isabs(path):raise ValueError('Destination needs a full drive path or a volume ID.')
    root=drive+'\\'
    if not root_available(root):return None
    identity=next((id for id,v in volumes.items() if (v.get('DriveLetter') or '').casefold()==drive.casefold()),drive.casefold())
    return (identity,drive.upper())

class Scheduler:
    """One run per availability/mapping transition; failures retry, successes stay idle."""
    def __init__(self):self.states={}
    def due(self,job,signature,now=None):
        now=time.monotonic() if now is None else now
        key=job['id']
        if not signature:
            self.states.pop(key,None)
            return False
        state=self.states.get(key)
        if state is None or state['signature']!=signature:
            state=dict(signature=signature,deadline=now+max(0,float(job.get('delay',3))),done=False)
            self.states[key]=state
        return not state['done'] and now>=state['deadline']
    def finish(self,job,success,now=None):
        state=self.states.get(job['id'])
        if state:
            state['done']=success
            state['deadline']=(time.monotonic() if now is None else now)+max(5,float(job.get('retry_seconds',60)))
