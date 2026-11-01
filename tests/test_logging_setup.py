from pathlib import Path
import logging
import os
import tempfile
import unittest
from unittest.mock import patch

from waraq.logging_setup import configure_logging, data_directory


class LoggingTests(unittest.TestCase):
    def test_override_directory_and_bounded_log(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"WARAQ_DATA_DIR": directory}):
            self.assertEqual(data_directory(), Path(directory))
            logger=logging.getLogger('waraqa')
            for handler in list(logger.handlers):handler.close();logger.removeHandler(handler)
            path=configure_logging();logging.getLogger('waraqa').error('diagnostic marker')
            for handler in logger.handlers:handler.flush()
            self.assertTrue(path.is_file());self.assertIn('diagnostic marker',path.read_text(encoding='utf-8'))
            self.assertLessEqual(logger.handlers[0].maxBytes,512_000)
            for handler in list(logger.handlers):handler.close();logger.removeHandler(handler)


if __name__=='__main__':unittest.main()
