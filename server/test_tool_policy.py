import unittest

from server.local_extensions import LocalTool, LocalToolRegistry
from server.tool_policy import ToolPolicy


class ToolPolicyTests(unittest.TestCase):
    def setUp(self):
        self.policy = ToolPolicy(LocalToolRegistry([
            LocalTool("platform_status", "状态", "读取状态"),
            LocalTool("search_workspace_files", "检索", "检索文件"),
            LocalTool("web_search", "网页检索", "检索网页"),
            LocalTool("write_file", "写入", "写入文件", risk="write_local"),
        ]))

    def test_selects_only_the_matching_read_only_tool(self):
        self.assertEqual([tool["id"] for tool in self.policy.resolve("请告诉我平台状态")], ["platform_status"])
        self.assertEqual([tool["id"] for tool in self.policy.resolve("帮我搜索文件")], ["search_workspace_files"])
        self.assertEqual([tool["id"] for tool in self.policy.resolve("搜索工作区中与配置有关的文件")], ["search_workspace_files"])
        self.assertEqual([tool["id"] for tool in self.policy.resolve("请搜索网页上的 Agent 新闻")], ["web_search"])

    def test_never_grants_write_tools_or_tools_without_an_intent(self):
        self.assertEqual(self.policy.resolve("请写入一个文件"), [])
        self.assertEqual(self.policy.resolve("你好"), [])


if __name__ == "__main__":
    unittest.main()
