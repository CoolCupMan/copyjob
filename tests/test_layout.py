import unittest
from automation import new_job,prepare_job,normalize_volume

A='\\\\?\\Volume{456e291b-0ff5-46a9-a4e1-e9c1f0adac5f}\\'
B='\\\\?\\Volume{58081618-0000-0000-0000-100000000000}\\'

class LayoutTests(unittest.TestCase):
    def setUp(self):
        self.job=new_job();self.job.update(source='C:\\Users\\Example\\ChatGPT\\134g32b5rg',destination='Z:\\CopyJobProgramTest')
    def test_selected_folder_and_all_descendants_have_a_container(self):
        self.assertEqual(prepare_job(self.job,{})[1],'Z:\\CopyJobProgramTest\\134g32b5rg')
        self.assertEqual(prepare_job(self.job,{})[1],prepare_job(self.job,{})[1])
    def test_contents_only_remains_available(self):
        self.job['layout']='contents'
        self.assertEqual(prepare_job(self.job,{})[1],'Z:\\CopyJobProgramTest')
    def test_full_path_keeps_parent_directory_hierarchy(self):
        self.job['layout']='full_path'
        self.assertEqual(prepare_job(self.job,{})[1],'Z:\\CopyJobProgramTest\\Users\\Example\\ChatGPT\\134g32b5rg')
    def test_volume_root_has_named_container(self):
        self.job['source']='C:\\'
        self.assertEqual(prepare_job(self.job,{})[1],'Z:\\CopyJobProgramTest\\Drive_C')
    def test_source_and_destination_hardware_filters_are_enforced(self):
        self.job.update(source='Documents',source_volume=A,source_serial='INTERNAL',source_interface='SCSI',destination='Backup',destination_volume=B,destination_serial='STICK',destination_interface='USB')
        volumes={normalize_volume(A):dict(DriveLetter='C:',Disks=[dict(SerialNumber=' INTERNAL ',InterfaceType='SCSI')]),normalize_volume(B):dict(DriveLetter='Z:',Disks=[dict(SerialNumber='STICK',InterfaceType='USB')])}
        self.assertEqual(prepare_job(self.job,volumes),('C:\\Documents','Z:\\Backup\\Documents'))
        for id in (normalize_volume(A),normalize_volume(B)):
            saved=volumes[id]['Disks'][0]['SerialNumber']
            volumes[id]['Disks'][0]['SerialNumber']='WRONG'
            with self.assertRaises(FileNotFoundError):prepare_job(self.job,volumes)
            volumes[id]['Disks'][0]['SerialNumber']=saved
