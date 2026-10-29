"""CopyJob's platform-independent copy engine."""
from pathlib import Path
import shutil
import uuid

VERSION = '1.3.1'
APP_ID = 'org.copyjob.desktop'


def new_config():
    return {'schema': 1, 'instance_id': str(uuid.uuid4()), 'version': VERSION,
            'source': '', 'destination': '', 'watch': False}


def validate(source, destination):
    if not source.strip() or not destination.strip():
        raise ValueError('Choose source and destination folders.')
    for value in (source, destination):
        raw = Path(value).absolute()
        for component in (raw, *raw.parents):
            if component.is_symlink() or getattr(component, 'is_junction', lambda: False)():
                raise ValueError('Selected paths must not contain links or junctions.')
    src, dst = Path(source).resolve(), Path(destination).resolve()
    if not src.is_dir():
        raise ValueError('Source folder is unavailable: '+str(src))
    if src == dst or src in dst.parents or dst in src.parents:
        raise ValueError('Source and destination must be separate, non-nested folders.')
    return src, dst


def copy_job(source, destination, log, cancelled):
    src, dst = validate(source, destination)
    copied = 0
    # Never follow links or junctions outside the selected tree.
    for root, dirs, files in __import__('os').walk(src, followlinks=False):
        if cancelled.is_set():
            raise InterruptedError('Copy cancelled; completed files are retained.')
        root = Path(root)
        dirs[:] = [d for d in dirs if not (root / d).is_symlink()
                   and not getattr(root / d, 'is_junction', lambda: False)()]
        target = dst / root.relative_to(src)
        if target.is_symlink() or getattr(target, 'is_junction', lambda: False)():
            raise ValueError('Destination contains a link or junction.')
        target.mkdir(parents=True, exist_ok=True)
        for name in files:
            if cancelled.is_set():
                raise InterruptedError('Copy cancelled; completed files are retained.')
            original, output = root / name, target / name
            if original.is_symlink():
                continue
            if output.is_symlink() or getattr(output, 'is_junction', lambda: False)():
                raise ValueError('Destination contains a link or junction.')
            if output.exists() and output.stat().st_mtime_ns >= original.stat().st_mtime_ns:
                continue
            # Stage beside the destination, then replace; failed copies keep the old file.
            temporary = target / ('.copyjob-' + str(uuid.uuid4()) + '.tmp')
            try:
                shutil.copy2(original, temporary)
                temporary.replace(output)
            finally:
                temporary.unlink(missing_ok=True)
            copied += 1
            log('Copied: ' + str(original.relative_to(src)))
    return copied
