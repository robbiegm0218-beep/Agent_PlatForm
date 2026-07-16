import unittest

from server.local_extensions import LocalTool, LocalToolRegistry
from server.tool_policy import ToolPolicy


class ToolPolicyTests(unittest.TestCase):
    def setUp(self):
        self.policy = ToolPolicy(LocalToolRegistry([
            LocalTool("platform_status", "状态", "读取状态"),
            LocalTool("search_workspace_files", "检索", "检索文件"),
            LocalTool("read_workspace_file", "读取", "读取文件内容"),
            LocalTool("web_search", "网页检索", "检索网页"),
            LocalTool("read_web_page", "读取网页", "读取网页正文"),
            LocalTool("write_file", "写入", "写入文件", risk="local_write"),
        ]))

    def test_selects_only_the_matching_read_only_tool(self):
        self.assertEqual([tool["id"] for tool in self.policy.resolve("请告诉我平台状态")], ["platform_status"])
        self.assertEqual([tool["id"] for tool in self.policy.resolve("帮我搜索文件")], ["search_workspace_files"])
        self.assertEqual([tool["id"] for tool in self.policy.resolve("搜索工作区中与配置有关的文件")], ["search_workspace_files"])
        self.assertEqual([tool["id"] for tool in self.policy.resolve("请搜索网页上的 Agent 新闻")], ["web_search"])
        self.assertEqual([tool["id"] for tool in self.policy.resolve("请帮我联网查一下最新 Agent 新闻")], ["web_search"])
        self.assertEqual([tool["id"] for tool in self.policy.resolve("帮我查一下，今天上海的天气")], ["web_search"])
        self.assertEqual([tool["id"] for tool in self.policy.resolve("帮我查一下：https://openai.com/zh-Hant-HK/index/harness-engineering/")], ["web_search"])
        self.assertEqual([tool["id"] for tool in self.policy.resolve("请读取工作区文件 README.md 的内容")], ["read_workspace_file"])
        self.assertEqual([tool["id"] for tool in self.policy.resolve("请读取并总结这个网页 https://example.com/page")], ["read_web_page"])

    def test_never_grants_write_tools_or_tools_without_an_intent(self):
        self.assertEqual(self.policy.resolve("请写入一个文件"), [])
        self.assertEqual(self.policy.resolve("你好"), [])

    def test_decision_explains_web_and_local_routing(self):
        web = self.policy.decide("请找一些公开资料并附上来源链接")
        self.assertEqual([tool["id"] for tool in web.tools], ["web_search"])
        self.assertEqual(web.confidence, "medium")
        self.assertIn("外部资料", web.reason)

        local = self.policy.decide("请查找工作区里的文件")
        self.assertEqual([tool["id"] for tool in local.tools], ["search_workspace_files"])
        self.assertIn("工作区", local.reason)

        ordinary = self.policy.decide("帮我解释什么是 Agent")
        self.assertEqual(ordinary.tools, [])
        self.assertEqual(ordinary.confidence, "none")


if __name__ == "__main__":
    unittest.main()
