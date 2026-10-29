from pathlib import Path
import unittest

class SetupTests(unittest.TestCase):
    def test_assignment_task_has_valid_windows_powershell_executable_path(self):
        text=(Path(__file__).resolve().parents[1]/'wmi_setup.ps1').read_text()
        self.assertNotIn(chr(11),text)
        self.assertIn(r'System32\WindowsPowerShell\v1.0\powershell.exe',text)
