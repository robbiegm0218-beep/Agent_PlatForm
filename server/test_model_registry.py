import unittest
from dataclasses import FrozenInstanceError

from server.model_registry import ModelCapabilities, ModelInfo, ModelRegistry, ProviderInfo


class ModelRegistryTests(unittest.TestCase):
    def setUp(self):
        self.registry = ModelRegistry()
        self.deepseek = ProviderInfo("deepseek", "DeepSeek", "DEEPSEEK_API_KEY", "https://api.deepseek.com")
        self.openai = ProviderInfo("openai", "OpenAI", "OPENAI_API_KEY")
        self.registry.register_provider(self.deepseek)
        self.registry.register_provider(self.openai)

    def test_provider_only_records_environment_variable_name(self):
        self.assertEqual(self.deepseek.env_var, "DEEPSEEK_API_KEY")
        with self.assertRaises(ValueError):
            ProviderInfo("bad", "Bad", "sk-secret-value")

    def test_descriptor_validation_and_immutability(self):
        with self.assertRaises(ValueError):
            ProviderInfo("bad id", "Bad", "API_KEY")
        with self.assertRaises(ValueError):
            ModelInfo("deepseek", "model", "Model", task_tier="other")
        with self.assertRaises(ValueError):
            ModelInfo("deepseek", "model", "Model", context_window=0)
        model = ModelInfo("deepseek", "model", "Model")
        with self.assertRaises(FrozenInstanceError):
            model.enabled = False

    def test_register_lookup_and_duplicate_rejection(self):
        model = ModelInfo("deepseek", "chat", "Chat", ModelCapabilities(streaming=True, tool_calling=True))
        self.registry.register_model(model)
        self.assertEqual(self.registry.lookup("deepseek", "chat"), model)
        with self.assertRaises(ValueError):
            self.registry.register_model(model)
        with self.assertRaises(ValueError):
            self.registry.register_model(ModelInfo("missing", "chat", "Missing"))

    def test_listing_is_deterministic_and_filters_disabled_models(self):
        self.registry.register_model(ModelInfo("openai", "first", "First"))
        self.registry.register_model(ModelInfo("deepseek", "disabled", "Disabled", enabled=False))
        self.registry.register_model(ModelInfo("deepseek", "last", "Last"))
        self.assertEqual([model.model_id for model in self.registry.list_models()], ["first", "last"])
        self.assertEqual([model.model_id for model in self.registry.list_models("deepseek", enabled_only=False)], ["disabled", "last"])
        self.assertEqual([provider.provider_id for provider in self.registry.list_providers()], ["deepseek", "openai"])


if __name__ == "__main__":
    unittest.main()
