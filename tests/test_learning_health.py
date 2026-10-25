import unittest
from studio.health import audit
from studio.learning import token_shape
class HealthLearningTests(unittest.TestCase):
 def test_name_shape(self):self.assertEqual(token_shape('Podcast_2026-10-25_Take02.wav'),'Podcast_{DATE}_Take{N}')
 def test_missing_hardware(self):
  h=audit('local',[],{'running':False},procs=[])
  codes={x['code'] for x in h['alerts']}
  self.assertIn('SCARLETT_MISSING',codes)
  self.assertIn('AUDITION_NOT_RUNNING',codes)
  self.assertIn('PHANTOM_UNVERIFIED',codes)
 def test_zoom_includes_selection_check(self):
  h=audit('zoom',[],{'running':False},procs=[])
  self.assertIn('ZOOM_SELECTION_UNVERIFIED',{x['code'] for x in h['alerts']})
if __name__=='__main__':unittest.main()
