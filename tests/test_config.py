import unittest
import tempfile
from pathlib import Path
from se02.config import load_config
from se02.domain import ValidationError

class ConfigTests(unittest.TestCase):
    def test_precedence(self):
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / 'config.toml'
            file.write_text('timeout = 12\nmodel = "file"\n', encoding='utf-8')
            config = load_config({'timeout': 30}, environ={'SE02_TIMEOUT': '20', 'SE02_MODEL': 'env'}, config_path=file)
            self.assertEqual(config.timeout, 30)
            self.assertEqual(config.model, 'env')
    def test_unknown_field_and_secret(self):
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / 'config.toml'
            file.write_text('api_key = "secret"', encoding='utf-8')
            with self.assertRaises(ValidationError):
                load_config({}, environ={}, config_path=file)
    def test_secret_not_repr(self):
        self.assertNotIn('sensitive-value', repr(load_config({}, environ={'SE02_API_KEY': 'sensitive-value'})))

class ConfigBoundsTests(unittest.TestCase):
    def test_invalid_values(self):
        for override in ({'timeout': 601}, {'timeout': True}, {'max_retries': 4}, {'max_repairs': 3}, {'retry_delay': 31}, {'base_url': 'http://example.com'}, {'base_url': 'https://user:secret@example.com'}):
            with self.subTest(override=override), self.assertRaises(ValidationError):
                load_config(override, environ={})
    def test_environment_numbers_and_defaults(self):
        result = load_config({}, environ={'SE02_MAX_RETRIES': '2', 'SE02_RETRY_DELAY': '1.5'})
        self.assertEqual(result.max_retries, 2)
        self.assertEqual(result.retry_delay, 1.5)
        self.assertIsNone(result.base_url)
        self.assertIsNone(result.model)
