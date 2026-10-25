import unittest
from studio.lifecycle import Lifecycle
class StubMonitor:
 def __init__(self):self.stopped=False
 def stop(self):self.stopped=True
 def snapshot(self):return {'running':False}
class PowerTests(unittest.TestCase):
 def test_default_off(self):
  lc=Lifecycle(StubMonitor());self.assertFalse(lc.snapshot()['on'])
 def test_on_off_without_external_services(self):
  from unittest.mock import patch
  m=StubMonitor();lc=Lifecycle(m)
  with patch('studio.lifecycle.shutil.which',return_value=None):
   self.assertTrue(lc.start('local')['on'])
  self.assertFalse(lc.stop()['on']);self.assertTrue(m.stopped)
 def test_invalid_mode(self):
  with self.assertRaises(ValueError):Lifecycle(StubMonitor()).start('bad')
if __name__=='__main__':unittest.main()
