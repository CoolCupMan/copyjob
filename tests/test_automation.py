import unittest
from automation import new_job,normalize_volume,prepare_job,xcopy_flags,Scheduler

ID=r'\\?\Volume{58081618-0000-0000-0000-100000000000}'+'\\'

class AutomationTests(unittest.TestCase):
    def setUp(self):
        self.job=new_job()
        self.job.update(source=r'C:\Users\Example\Documents',destination='Backup',destination_volume=ID,trigger_volume=ID)
        self.volumes={normalize_volume(ID):dict(DeviceID=ID,DriveLetter='E:')}

    def test_letter_change_resolves_same_volume(self):
        self.assertEqual(prepare_job(self.job,self.volumes)[1],r'E:\Backup')
        self.volumes[normalize_volume(ID)]['DriveLetter']='Z:'
        self.assertEqual(prepare_job(self.job,self.volumes)[1],r'Z:\Backup')

    def test_waits_for_letter_and_missing_volume(self):
        for volumes in [{},{normalize_volume(ID):dict(DriveLetter=None)}]:
            with self.assertRaises(FileNotFoundError):prepare_job(self.job,volumes)

    def test_rejects_invalid_id_and_escaping_relative_path(self):
        with self.assertRaises(ValueError):normalize_volume('E:')
        self.job['destination']=r'..\outside'
        with self.assertRaises(ValueError):prepare_job(self.job,self.volumes)

    def test_flags_and_prompt_prevention(self):
        self.assertIn('/Y',xcopy_flags(self.job))
        for flag in ['/W','/-Y','/FAKE','& calc.exe']:
            self.job['extra_flags']=flag
            with self.assertRaises(ValueError):xcopy_flags(self.job)
        self.job['extra_flags']='/D:10-29-2026 /EXCLUDE:C:\\exclude.txt'
        self.assertIn('/EXCLUDE:C:\\exclude.txt',xcopy_flags(self.job))

    def test_exclude_file_with_spaces(self):
        self.job['extra_flags']='/EXCLUDE:"C:\\My Files\\exclude.txt"'
        self.assertIn('/EXCLUDE:C:\\My Files\\exclude.txt',xcopy_flags(self.job))

    def test_reboot_initial_run_and_no_duplicate_until_reconnect(self):
        scheduler=Scheduler()
        self.assertFalse(scheduler.due(self.job,('E:',),now=0))
        self.assertTrue(scheduler.due(self.job,('E:',),now=3))
        scheduler.finish(self.job,True,now=3)
        self.assertFalse(scheduler.due(self.job,('E:',),now=1000))
        self.assertFalse(scheduler.due(self.job,None,now=1001))
        self.assertFalse(scheduler.due(self.job,('E:',),now=1002))
        self.assertTrue(scheduler.due(self.job,('E:',),now=1005))
        self.assertFalse(scheduler.due(self.job,('Z:',),now=1006))
        self.assertTrue(scheduler.due(self.job,('Z:',),now=1009))

    def test_failed_copy_retries(self):
        scheduler=Scheduler();scheduler.due(self.job,'ready',now=0)
        scheduler.finish(self.job,False,now=3)
        self.assertFalse(scheduler.due(self.job,'ready',now=62))
        self.assertTrue(scheduler.due(self.job,'ready',now=63))

if __name__=='__main__':unittest.main()
