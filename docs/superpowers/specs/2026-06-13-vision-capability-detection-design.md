# Argos 视觉能力检测 — 设计(懒触发探针 + 缓存)

- 日期：2026-06-13
- 状态：设计已定稿,待实现
- 关联:`core/models.py`(`ModelTier`)、`config.py`、`core/loop.py`(多模态门 @723)、`core/protocols.py`(图片物化)、`input/attachments.py`、`setup_wizard.py`(现有探针样板)
- 背景调研:`docs/superpowers/specs/2026-06-13-voice-image-input-design.md`(图片输入)+ 两轮生态调研(无人内联探针;Claude Code 躲、Hermes 静态表 models.dev + 降级)

## 1. 背景与目标

图片输入已落地(Plan 1+2),但模型"支不支持视觉"目前靠 `ModelTier.multimodal: bool`(默认 False)这个**手填声明**判定。它有两个真问题:

1. **`config.py` 根本没读这个字段**(`config.py:189` 建 `ModelTier` 时丢了 `multimodal`),所以手填 `"multimodal": true` 当前被静默忽略。
2. 即便修好读取,**手填声明违背 Argos "凡事验证、别信自述" 的灵魂**,且对代理/聚合别名(如 `agnes-2.0-flash`)天然失效,更**抓不住"静默吞图"**(纯文本端点收下请求、丢掉图、照样自信作答的假绿灯——生态调研三个实锤,集中在代理层)。

目标:把"能力判定"从**手填声明**改成**懒触发的、有标准答案的探针 + 缓存**——能力靠真实使用自发现、每模型只探一次、确定性核对、绝不假绿灯。这是 verify-gate 灵魂在视觉上的复刻。

## 2. 决策摘要(已锁定)

1. **哲学**:不提前声明能力;第一次给某 `(base_url, model)` 发图时,先用一张**已知答案的图**探一次,结果缓存。
2. **探针图**:纯色填充 PNG,颜色从 6 个名字稳定的明显色(red/green/blue/yellow/black/white)中**随机**选一(盲模型 1/6 蒙不中);颜色可注入(测试确定性)。问"主色?只回颜色词",核对答案含该色名(带小同义集)。
3. **失败 = 诚实硬阻断**:探出"看不了图"(答错/答"看不到"/API 报错/网络失败)→ 不发请求,诚实告知用户换视觉模型或配 override。沿用现有 gate 语义。
4. **`multimodal` 降级为可选 override**:`ModelTier.multimodal: bool | None`,`None`=未知→探针;`True/False`=用户显式 override(最高优先级,跳探针)。**这就是 "unknown ≠ False" 的落地**。
5. **缓存**:独立 `~/.argos/vision_cache.json`,键 `(base_url, model)`;机器探测结果与用户声明(config.json)分开。
6. **范围 YAGNI**:v1 不做 registry 快路径(models.dev)、不做 setup 主动探针、不做 Hermes 式转描述降级——留后续。

## 3. 架构总览

```
用户附图 → loop.run 见 attachments(@1077 起)
  → await resolve_vision_capability(tier, model_client, cache):
       ① tier.multimodal is not None  → 用 override(跳探针)
       ② cache 命中 (base_url, model) → 用缓存
       ③ 否则 → await VisionProbe.run(model_client)  # 发随机色图、核对
                 → 写缓存 → 返回
  → True  → 走现有附件物化路径(protocols.payload 出 image block)
  → False → raise 诚实错误 → 顶层兜底转 Error 事件
            ("当前模型 X 看不了图——换个视觉模型,或在 config 设 multimodal override")
```

无递归:`VisionProbe` 直接调 `model_client.complete`(协议层照常物化图片,门只在 `loop.run`),不回 `loop.run`。

## 4. 组件设计(新模块 `argos/core/vision_capability.py`)

高内聚、可独立测试,三件:

### 4.1 `VisionProbe`
```
class VisionProbe:
    def __init__(self, *, color: str | None = None): ...   # None=随机;注入色做测试
    async def run(self, model_client) -> bool: ...
```
- 生成纯 `color` 填充的小 PNG(stdlib zlib+struct,无需 PIL;复用图片生成思路)。
- 构造 `[{"role":"user","content":"What is the dominant color of this image? Reply with ONLY the color word.","attachments":[ImageAttachment(png,...)]}]`,`await model_client.complete(msgs, system="You are a vision capability test.")`。
- 核对:期望色名(或其小同义集,如 grey/gray)出现在 `response.lower()` → `True`;否则 `False`。
- **任何异常(网络/API/400)→ `False`(不可验即不支持,绝不假设 yes)**。

### 4.2 `VisionCapabilityCache`
```
class VisionCapabilityCache:
    def __init__(self, path: Path | None = None): ...   # 默认 ~/.argos/vision_cache.json
    def get(self, base_url: str, model: str) -> bool | None: ...   # 未缓存=None
    def set(self, base_url: str, model: str, verified: bool) -> None: ...
```
- 落盘 schema:`{ "<base_url>": { "<model>": {"verified": bool, "ts": float} } }`(嵌套、可读;`ts` 记录探测时刻,供未来 TTL/失效,v1 不消费)。
- 读写 best-effort(沿用 `config_base.py` 风格);畸形/缺文件 → 视为空缓存(`get` 返 None),不崩。

### 4.3 `resolve_vision_capability`
```
async def resolve_vision_capability(tier, model_client, cache, *, probe=None) -> bool:
    if tier.multimodal is not None:        # L0 override
        return tier.multimodal
    cached = cache.get(tier.base_url, tier.model)
    if cached is not None:                 # 缓存命中
        return cached
    verified = await (probe or VisionProbe()).run(model_client)   # 探针(probe 可注入)
    cache.set(tier.base_url, tier.model, verified)
    return verified
```
单一入口,替代所有 `tier.multimodal` 读点。`probe` 参数可注入(测试不发真网络)。

## 5. ModelTier 三态 + config 读取

- `core/models.py`:`ModelTier.multimodal: bool = False` → **`multimodal: bool | None = None`**(三态)。`None`=未知→探针;`True/False`=override。
- `config.py:189`:`ModelTier(...)` 增 `multimodal=m.get("multimodal")`(未设→`None`,即默认走探针;不再被丢)。
- 兼容:既有构造点不传 `multimodal` → 默认 `None`(走探针),零破坏。

## 6. loop.py 门接线

`core/loop.py:723-730` 现状:
```python
if attachments:
    tier = getattr(getattr(self, "_model", None), "tier", None)
    if tier is not None and not getattr(tier, "multimodal", False):
        raise ValueError("当前模型 ... 不支持图像输入(multimodal=False)...")
```
改为:
```python
if attachments:
    tier = getattr(getattr(self, "_model", None), "tier", None)
    if tier is not None:
        from argos.core.vision_capability import resolve_vision_capability, VisionCapabilityCache
        ok = await resolve_vision_capability(tier, self._model, VisionCapabilityCache())
        if not ok:
            raise ValueError(f"当前模型 {tier.model!r} 看不了图(已探测/缓存)——"
                             "请换个支持视觉的模型,或在 config 给该 profile 设 multimodal override。")
```
门仍在发请求前;`raise` 经 `run()` 顶层兜底转 Error 事件(inline `_produce` catch + daemon worker `mark_failed` 都已验证安全,无需移门)。首次用图多一次探针调用(之后缓存,免探)。

## 7. 诚实与失败模式(产品铁律)

- 探针**确定性**(已知随机色,有标准答案)——能抓"静默吞图":吞图模型答不出/瞎答非该色 → 判 False。
- 探针**网络/API 失败 → False**(不可验即不支持,绝不假设 yes)。
- override 永远最高优先级(用户明确知道时的逃生口)。
- 缓存按 `(base_url, model)` —— 代理别名各有各的状态,换模型重探。
- 并发:两 run 同时探同一未缓存模型 → 各探一次(幂等,至多多探一次),v1 接受。

## 8. 测试策略(TDD,80% 覆盖门)

- `VisionProbe`(注入 fake model_client):答"red"+color="red" → True;答"I can't see any image" → False;答错色 → False;client 抛 → False;断言确实发了带 attachments 的消息。
- `VisionCapabilityCache`(tmp path):set→get 往返;未缓存→None;畸形 json→空缓存不崩;按 (base_url,model) 隔离。
- `resolve_vision_capability`(注入 fake probe + cache):override(True/False)短路、不探;缓存命中不探;miss → 探一次 + 写缓存;探针返回值被缓存。
- 门集成:`loop.run` 带 attachments + resolve→False → yield Error(诚实错误文案);resolve→True → 正常进 drive(用 monkeypatch resolve 或注入 cache 命中,避免真探针)。
- `config.py`:读 `multimodal` 三态(未设→None;true→True;false→False)。
- `core/models.py`:`ModelTier(multimodal=None)` 默认;可设 True/False/None。
- `@pytest.mark.slow`:真模型探针(CI 跳过,诚实标注 unverifiable)。

## 9. 范围与分期(YAGNI)

- **v1**:第 4–8 节全部——懒探针 + 缓存 + 三态 override + 诚实硬阻断。
- **后续**:registry 快路径(导 models.dev,已知官方非视觉模型省探针);setup 向导主动探针(写缓存);Hermes 式转描述降级(需 vision_analyze 工具 + 可用视觉模型)。
- **明确不做**:把探测结果写回 config.json(机器/用户声明混淆);多图 canary;TTL 失效(ts 记录但不消费)。

## 10. 触及文件清单

- 新增:`argos/core/vision_capability.py`(VisionProbe + VisionCapabilityCache + resolve_vision_capability)
- 改:`argos/core/models.py`(`ModelTier.multimodal: bool | None = None`)、`argos/config.py`(`ModelTier(...)` 读 `multimodal` override)、`argos/core/loop.py`(门 @723 改用 `resolve_vision_capability`,门内 `await`)
- 配置:`~/.argos/vision_cache.json`(新缓存文件,运行时生成)
- 测试:`tests/core/test_vision_capability.py`(probe/cache/resolve)、`tests/test_loop_attachments.py` 扩(门走 resolve)、`tests/test_models_multimodal.py` 扩(三态)、`config` 三态测试

## 11. 验收标准

1. config.json 设 `"multimodal": true` → 真生效(override,跳探针、放行图);设 `false` → 阻断。**(修当前 bug)**
2. 未设 `multimodal` + 真视觉模型(如 agnes-2.0-flash)首次发图 → 探针判 True → 放行 + 缓存;二次发图不再探。
3. 未设 + 纯文本/静默吞图模型 → 探针判 False → 诚实硬阻断,给可操作文案,绝不 fake-green。
4. 探针网络失败 → 判 False(阻断),不假设支持。
5. 缓存按 (base_url, model) 隔离;换 base_url/model 重探。
6. 无附件请求 → 不触发探针、不读缓存(零额外开销、零回归)。
7. `uv run pytest` 全绿,覆盖 ≥ 80%。
