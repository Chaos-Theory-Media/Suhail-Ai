import unittest
from sawti import agent_status,respond
class SawtiTests(unittest.TestCase):
 def test_missing_hardware(self):
  d=agent_status('local',[],{'running':False}, {})
  self.assertEqual(d[0]['state'],'fail')
 def test_fault_help(self):
  ans=respond('mic 1 silent','local',{'checks':[]})
  self.assertIn('gain knob',ans['reply'])
 def test_zoom_help(self):
  ans=respond('check zoom','zoom',{'checks':[]})
  self.assertIn('BlackHole',ans['reply'])
if __name__=='__main__':unittest.main()
