import unittest
from dataclasses import FrozenInstanceError

from server.provider_config import parse_provider_configs


class ProviderConfigTests(unittest.TestCase):
    RAW = '''[{"provider_id":"openai","display_name":"OpenAI","api_key_env":"OPENAI_API_KEY","base_url":"https://api.openai.com/v1/","models":["gpt-4.1","gpt-4.1-mini"]}]'''

    def test_blank_is_empty_and_valid_config_is_normalized(self):
        self.assertEqual(parse_provider_configs(""), [])
        config = parse_provider_configs(self.RAW)[0]
        self.assertEqual(config.base_url, "https://api.openai.com/v1")
        self.assertEqual(config.models, ("gpt-4.1", "gpt-4.1-mini"))
        with self.assertRaises(FrozenInstanceError):
            config.provider_id = "other"

    def test_rejects_invalid_json_shape_and_duplicates(self):
        for raw in ("{", "{}", '[{"provider_id":"p","display_name":"P","api_key_env":"P_KEY","base_url":"https://x.test","models":[]}]'):
            with self.assertRaises(ValueError):
                parse_provider_configs(raw)
        duplicate = '''[
          {"provider_id":"p","display_name":"P","api_key_env":"P_KEY","base_url":"https://p.test","models":["m"]},
          {"provider_id":"p","display_name":"P2","api_key_env":"P2_KEY","base_url":"https://p2.test","models":["m2"]}
        ]'''
        with self.assertRaises(ValueError):
            parse_provider_configs(duplicate)

    def test_rejects_secrets_non_https_and_invalid_model_ids(self):
        for field, value in (("api_key_env", "sk-secret"), ("base_url", "http://example.test"), ("models", ["bad id"])):
            raw = self.RAW.replace('"OPENAI_API_KEY"', f'"{value}"') if field == "api_key_env" else self.RAW.replace('"https://api.openai.com/v1/"', f'"{value}"') if field == "base_url" else self.RAW.replace('["gpt-4.1","gpt-4.1-mini"]', '["bad id"]')
            with self.assertRaises(ValueError):
                parse_provider_configs(raw)


if __name__ == "__main__":
    unittest.main()
