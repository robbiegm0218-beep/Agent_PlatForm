import unittest

from server.model_provider import DeepSeekConfig, DeepSeekProvider


class FakeResponse:
    def __init__(self, lines):
        self._lines = lines

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc_value, _traceback):
        return False

    def __iter__(self):
        return iter(self._lines)


class StubDeepSeekProvider(DeepSeekProvider):
    def __init__(self, lines):
        super().__init__(DeepSeekConfig(api_key="test", base_url="https://example.test"))
        self._lines = lines

    def _open_stream(self, _messages, _tools, _model, _max_output_tokens):
        return FakeResponse(self._lines)


class DeepSeekProviderTests(unittest.TestCase):
    @staticmethod
    def sse(payload):
        return f"data: {payload}\n\n".encode("utf-8")

    def test_complete_assembles_content_and_fragmented_tool_call(self):
        provider = StubDeepSeekProvider([
            self.sse('{"choices":[{"delta":{"content":"你好"}}]}'),
            self.sse('{"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_1","function":{"name":"sea"}}]}}]}'),
            self.sse('{"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"name":"rch","arguments":"{\\"q\\":\\"x"}}]}}]}'),
            self.sse('{"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"\\"}"}}]}}]}'),
            self.sse('[DONE]'),
        ])

        message = provider.complete([], [], "test", 100)

        self.assertEqual(message["content"], "你好")
        self.assertEqual(message["tool_calls"][0]["id"], "call_1")
        self.assertEqual(message["tool_calls"][0]["function"], {"name": "search", "arguments": '{"q":"x"}'})

    def test_stream_yields_deltas_then_a_complete_message(self):
        provider = StubDeepSeekProvider([
            self.sse('{"choices":[{"delta":{"content":"A"}}]}'),
            self.sse('{"choices":[{"delta":{"content":"B"}}]}'),
            self.sse('[DONE]'),
        ])

        events = list(provider.stream([], [], "test", 100))

        self.assertEqual(events[:2], [{"type": "content", "text": "A"}, {"type": "content", "text": "B"}])
        self.assertEqual(events[-1]["message"], {"role": "assistant", "content": "AB", "tool_calls": None})


if __name__ == "__main__":
    unittest.main()
