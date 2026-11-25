## 改了什么

<!-- 一句话 -->

## 为什么

<!--
  关联的 issue 编号 / ADR 编号 / known-limitations 条目编号。
  如果这是一个有取舍的技术选择，
  请说明是否需要补一条 ADR（见 CONTRIBUTING.md §4.4）。
-->

Closes #

## 怎么验证的

<!--
  贴出实际跑过的命令与**实测数字**。
  不要写"测试通过"这种没有数字的话。
-->

```powershell
# 端侧
python -m pytest core\tests -q
# 实测：___ 项全过，___ 失败，___ 跳过

# 云端
cd core\cloud && mvn test
# 实测：___ 项全过，BUILD ___

# 协议一致性
powershell -ExecutionPolicy Bypass -File core\scripts\validate-protocol.ps1
# 实测：___ 条样例

# 端到端与评测门禁（若涉及）
powershell -ExecutionPolicy Bypass -File core\scripts\e2e.ps1
powershell -ExecutionPolicy Bypass -File core\scripts\eval.ps1
# 实测：
```

## 影响面

<!--
  改了哪些接口 / 类？
  是否破坏向后兼容？
  调用方需配合的修改？
  旧代码能否与新代码共存？
-->

## 已知限制是否变化

- [ ] 未涉及能力边界
- [ ] 已同步更新 `docs/known-limitations.md`（条目编号：______）
- [ ] 本 PR **暴露**了新的能力边界（请在说明里写清"现在不成立的是哪一条"）
