# 记忆系统——Markdown 文件层

本文档保留 Markdown 记忆层的当前入口；旧的滑动近期摘要实现已退役，不能作为运行时状态清单。

## 文件

| 路径（`memory/` 下） | 用途 |
|------|------|
| `SELF.md` | Akashic 自我认知（人格与形象 / 对用户的理解 / 关系定义），常驻 |
| `PROFILE.md` | 用户画像（用户事实 / 用户偏好 / 明确要求记住的内容），常驻，默认 3000 字配额 |
| `topics/<名>.md` | 全局主题；frontmatter 含 `description`（可选 `pinned`） |
| `topics/<文件夹>/_scope.md` | 文件夹归属：`scope: project=p_…` 与 `description`；文件夹名由模型自取 |
| `topics/<文件夹>/<名>.md` | 该 scope（会话宽键，如项目）专属主题 |

旧布局 `MEMORY.md`、非空的 `PENDING.md` / `PENDING.snapshot.md`、未完成的旧版 draft 会让插件拒绝启动：
升级前手动把 `MEMORY.md` 拆分为 `PROFILE.md` 与 `topics/` 并移走原文件。

## 后台提炼

Output 引用压缩摘要后，follower 读取尚未学习的完整 Turn，把当前 `SELF.md`、`PROFILE.md`、全局主题与本 scope
文件夹全文交给模型，模型只返回操作：`add`、`supersede`、`retract`、`create`、`create_folder`。

- 证据：每个操作引用本次来源的真实 message_id；`PROFILE.md`、`SELF.md` 中对用户与关系的判断及 `retract` 只认用户 Input。
- 新条目为不超过 120 字的单行 `- ` 文本；配额只在内容变长时检查，既有手写内容不阻断提炼。不合格草稿修正一次。
- 只能写全局主题或当前 scope 的文件夹；后台不设置 `pinned`。

```
compaction summary used by Output
  → markdown_ops_v1（操作 draft，按 source_ref 幂等）
  → 文件锁内叠加到当前文件（幂等收敛：已存在跳过、旧条目不在则 noop、同 scope 已有文件夹则重定向）
  → markdown_before_v1（首次叠加前内容）+ markdown_ops_applied_v1
```

叠加作用于锁内读到的当前文件，agent 或人工的并发修改不会被覆盖；崩溃后启动时重放未确认的 draft。
消息正文只追加，压缩不 UPDATE/DELETE 既有消息。
