import unittest
from studio.engine import profile,select_device,preflight
class EngineTests(unittest.TestCase):
 def test_profiles(self):
  self.assertEqual(profile('local')['required_input_channels'],4)
  self.assertEqual(profile('zoom')['required_input_channels'],4)
 def test_matching(self):
  ds=[{'name':'Scarlett 18i8 USB','inputs':18,'outputs':8,'default_rate':48000}]
  self.assertEqual(select_device(ds,profile('local'))['name'],'Scarlett 18i8 USB')
 def test_missing(self):
  self.assertIsNone(select_device([],profile('zoom')))
if __name__=='__main__':unittest.main()
