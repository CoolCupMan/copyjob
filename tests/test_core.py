import tempfile
import threading
import unittest
from pathlib import Path
from core import copy_job, new_config, validate

class CopyTests(unittest.TestCase):
    def test_independent_identity(self):
        self.assertNotEqual(new_config()['instance_id'], new_config()['instance_id'])

    def test_copy_preserves_newer_and_does_not_delete(self):
        with tempfile.TemporaryDirectory() as directory:
            src, dst = Path(directory)/'src', Path(directory)/'dst'
            src.mkdir(); dst.mkdir()
            (src/'hello').write_text('hello')
            (dst/'extra').write_text('keep')
            self.assertEqual(copy_job(str(src), str(dst), lambda _: None, threading.Event()), 1)
            self.assertEqual((dst/'hello').read_text(), 'hello')
            self.assertEqual(copy_job(str(src), str(dst), lambda _: None, threading.Event()), 0)
            self.assertTrue((dst/'extra').exists())

    def test_rejects_nested_and_blank_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            for a,b in [(directory,directory), (directory,directory+'/child'), ('',directory)]:
                with self.assertRaises(ValueError): validate(a,b)

    def test_cancellation(self):
        with tempfile.TemporaryDirectory() as directory:
            src = Path(directory)/'src'; src.mkdir()
            event = threading.Event(); event.set()
            with self.assertRaises(InterruptedError):
                copy_job(str(src), str(Path(directory)/'dst'), lambda _:None, event)

    def test_source_links_are_skipped(self):
        with tempfile.TemporaryDirectory() as directory:
            src = Path(directory)/'src'; src.mkdir()
            outside = Path(directory)/'private'; outside.write_text('secret')
            try: (src/'link').symlink_to(outside)
            except OSError: self.skipTest('Symlinks unavailable')
            dst = Path(directory)/'dst'
            self.assertEqual(copy_job(str(src),str(dst),lambda _:None,threading.Event()),0)
            self.assertFalse((dst/'link').exists())

if __name__ == '__main__': unittest.main()
