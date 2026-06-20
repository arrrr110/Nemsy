# Nemsy 测试

## 烟雾测试（Smoke Test）

快速验证核心功能是否正常工作的轻量级测试。

### 运行方式

**方式 1：使用命令行工具（推荐）**

```bash
nemsy-smoke
```

**方式 2：直接运行 pytest**

```bash
pytest tests/test_smoke.py -v -s
```

**方式 3：直接执行脚本**

```bash
python tests/test_smoke.py
```

### 测试内容

- ✅ `ingest` 基本功能：摄取测试文件，验证生成的 Wiki 页面格式
- ✅ `query` 基本功能：查询 Wiki 内容，验证返回答案
- ✅ `query` 归档功能：验证 `--archive` 参数正常工作

### 注意事项

1. **测试会调用真实的 LLM API**，会产生 token 消费
2. **测试会生成 Wiki 内容**，测试完成后需手动清理：
   ```bash
   # 清理测试生成的文件
   rm nemsy-wiki/sources/test-*
   rm nemsy-wiki/sources/测试*
   rm nemsy-wiki/queries/*$(date +%Y-%m-%d).md
   ```
3. 测试运行时间取决于 LLM API 响应速度，通常 30-60 秒

### 开发建议

- 每次修改核心逻辑（`agent.py`、`vault.py`）后运行一次烟雾测试
- 测试失败时检查 API 配置和 Vault 路径是否正确
- 可以根据需要在 `test_smoke.py` 中添加更多测试用例
