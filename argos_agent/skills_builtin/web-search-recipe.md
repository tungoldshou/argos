---
name: web-search-recipe
description: 用 web_search + web_extract 组合查资料
trust: builtin
enabled: true
---

# web-search-recipe

1. `web_search(query="...", limit=5)` 拿 URL 列表
2. 对最相关 1-2 个用 `web_extract(url=...)` 拿正文
3. 综合后引用 URL 给用户
4. **绝不**编造未在搜索结果中的事实
