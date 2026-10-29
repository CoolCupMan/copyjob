import unittest
from automation import new_job,normalize_volume,trigger_signature,prepare_job
from drive_events import DriveEvents

ID='\\\\?\\Volume{58081618-0000-0000-0000-100000000000}\\'

class MatchingTests(unittest.TestCase):
    def setUp(self):
        self.job=new_job();self.job.update(trigger_volume=ID,trigger_serial='NAASPZ2N',trigger_interface='USB',source='C:\\Documents',destination='Z:\\Backup')
        self.volume=dict(DriveLetter='Z:',Disks=[dict(SerialNumber='  NAASPZ2N  ',InterfaceType='USB')])
        self.volumes={normalize_volume(ID):self.volume}
    def test_exact_volume_usb_and_trimmed_serial_match(self):
        self.assertEqual(trigger_signature(self.job,self.volumes,lambda _:True),(normalize_volume(ID),'Z:'))
        self.job['trigger_serial']='naaspz2n'
        self.assertIsNotNone(trigger_signature(self.job,self.volumes,lambda _:True))
    def test_wrong_disk_cannot_trigger_or_run_manually(self):
        self.volume['Disks'][0]['SerialNumber']='OTHER'
        self.assertIsNone(trigger_signature(self.job,self.volumes,lambda _:True))
        with self.assertRaises(FileNotFoundError):prepare_job(self.job,self.volumes)
    def test_usb_and_serial_must_match_same_physical_disk(self):
        self.volume['Disks']=[dict(SerialNumber='NAASPZ2N',InterfaceType='SCSI'),dict(SerialNumber='OTHER',InterfaceType='USB')]
        self.assertIsNone(trigger_signature(self.job,self.volumes,lambda _:True))
    def test_missing_hardware_metadata_does_not_weaken_filter(self):
        self.volume['Disks']=[]
        self.assertIsNone(trigger_signature(self.job,self.volumes,lambda _:True))
        self.job.update(trigger_serial='',trigger_interface='')
        self.assertIsNotNone(trigger_signature(self.job,self.volumes,lambda _:True))
    def test_content_configuration_event_is_ignored(self):
        events=DriveEvents(lambda _:None)
        events.record('Z:',1)
        self.assertEqual(events.generation('Z:'),0)
        events.record('Z:',3);events.record('Z:',2)
        self.assertEqual(events.generation('Z:'),2)
        self.assertEqual(events.generation('E:'),0)

if __name__=='__main__':unittest.main()
