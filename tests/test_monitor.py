"""End-to-end monitor scheduling without depending on Windows WMI availability."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from automation import new_job,normalize_volume,trigger_signature
from windows_runtime import watch

ID='\\\\?\\Volume{58081618-0000-0000-0000-100000000000}\\'
OTHER='\\\\?\\Volume{456e291b-0ff5-46a9-a4e1-e9c1f0adac5f}\\'

class MonitorTests(unittest.TestCase):
    def test_only_selected_drive_arrival_or_letter_retriggers(self):
        with tempfile.TemporaryDirectory() as temporary:
            base=Path(temporary)
            job=new_job();job.update(enabled=True,delay=0,trigger_volume=ID,destination_volume=OTHER,source='Documents',destination='Backup')
            config={'jobs':[job]}
            def save():(base/'instance.json').write_text(json.dumps(config),encoding='utf-8')
            save()
            volumes={normalize_volume(ID):dict(DriveLetter='E:'),normalize_volume(OTHER):dict(DriveLetter='F:')}
            calls=[]
            class Stop:
                step=0
                def is_set(self):return self.step>=7
                def wait(self,_):
                    self.step+=1
                    if self.step==1:(base/'changed-source-file.txt').write_text('new contents')
                    elif self.step==2:job.update(source='Different source',destination='Different target',flags=['L']);save()
                    elif self.step==3:volumes[normalize_volume(OTHER)]['DriveLetter']='G:'
                    elif self.step==4:volumes.pop(normalize_volume(ID))
                    elif self.step==5:volumes[normalize_volume(ID)]=dict(DriveLetter='E:')
                    elif self.step==6:volumes[normalize_volume(ID)]['DriveLetter']='Z:'
            stop=Stop()
            def run(*_):calls.append((stop.step,volumes[normalize_volume(ID)]['DriveLetter']));return True
            with patch('windows_runtime.inventory',lambda:volumes),patch('windows_runtime.run_job',run):
                watch(base,stop,lambda _:None)
            self.assertEqual(calls,[(0,'E:'),(5,'E:'),(6,'Z:')])

    def test_fixed_destination_folder_does_not_change_drive_trigger(self):
        job=new_job();job['destination']='E:\\Backup'
        volumes={normalize_volume(ID):dict(DriveLetter='E:')}
        before=trigger_signature(job,volumes,lambda _:True)
        job['destination']='E:\\Other backup'
        self.assertEqual(trigger_signature(job,volumes,lambda _:True),before)
        self.assertIsNone(trigger_signature(job,volumes,lambda _:False))

if __name__=='__main__':unittest.main()
