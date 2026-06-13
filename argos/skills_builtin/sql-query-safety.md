---
name: sql-query-safety
description: 只读 SQL,带 LIMIT,绝不 DROP/DELETE/UPDATE
trust: builtin
enabled: true
---

# sql-query-safety

- 任何 SQL 必带 `LIMIT 100`
- 关键字 DROP/DELETE/UPDATE/INSERT/ALTER/TRUNCATE/CREATE/REPLACE 一律改写或拒绝
- 不明 schema 时先 `information_schema.columns` 看列
