import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from windows_runtime import _run_job
from automation import new_job

class DirectoryPhaseTests(unittest.TestCase):
    def fixture(self,folder):
        source=Path(folder)/'ChatGPT';source.mkdir()
        (source/'empty').mkdir();(source/'nested').mkdir()
        (source/'nested'/'file.txt').write_text('contents')
        destination=Path(folder)/'backup'/'ChatGPT'
        job=new_job();job.update(source=str(source),destination=str(destination),flags=['E','H','K','Y','I'])
        return source,destination,job
    def test_directory_phase_precedes_file_phase_without_changing_file_switches(self):
        with tempfile.TemporaryDirectory() as folder:
            source,destination,job=self.fixture(folder)
            commands=[]
            def native(command,*_):
                commands.append(command)
                if '/T' in command:
                    (destination/'empty').mkdir();(destination/'nested').mkdir()
                else:
                    self.assertTrue((destination/'empty').is_dir())
                    (destination/'nested'/'file.txt').write_text('contents')
                return 0
            with patch('windows_runtime.prepare_job',return_value=(str(source),str(destination))),patch('windows_runtime.native_command',side_effect=native):
                self.assertTrue(_run_job(job,{},lambda _:None,threading.Event()))
            self.assertEqual(len(commands),2)
            self.assertEqual(commands[0][:-1],commands[1])
            self.assertEqual(commands[0][-1],'/T')
            self.assertEqual((destination/'nested'/'file.txt').read_text(),'contents')
    def test_preview_does_not_create_destination_or_run_directory_phase(self):
        with tempfile.TemporaryDirectory() as folder:
            source,destination,job=self.fixture(folder);job['flags'].append('L')
            with patch('windows_runtime.prepare_job',return_value=(str(source),str(destination))),patch('windows_runtime.native_command',return_value=0) as native:
                self.assertTrue(_run_job(job,{},lambda _:None,threading.Event()))
            self.assertEqual(native.call_count,1)
            self.assertNotIn('/T',native.call_args.args[0])
            self.assertFalse(destination.exists())
    def test_failed_directory_phase_stops_before_file_copy(self):
        with tempfile.TemporaryDirectory() as folder:
            source,destination,job=self.fixture(folder)
            with patch('windows_runtime.prepare_job',return_value=(str(source),str(destination))),patch('windows_runtime.native_command',return_value=4) as native:
                with self.assertRaisesRegex(RuntimeError,'Directory creation failed'):
                    _run_job(job,{},lambda _:None,threading.Event())
            self.assertEqual(native.call_count,1)
