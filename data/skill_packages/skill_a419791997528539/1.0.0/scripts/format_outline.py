#!/usr/bin/env python3
"""Print a deterministic research-brief outline for a supplied topic."""

import sys


topic = " ".join(sys.argv[1:]).strip() or "未命名主题"
print(f"# {topic}\n\n## Question\n\n## Evidence\n\n## Analysis\n\n## Uncertainty\n\n## Recommendation and next step")
