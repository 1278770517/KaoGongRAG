# 考公 RAG 测试工作台

本目录是 Vue 3 + TypeScript + Tailwind CSS 测试前端。接口以 `../docs/frontend-api-contract.md` 和 `../docs/openapi.snapshot.json` 为准。

## 本地启动

```powershell
cd D:\KaoGongRAG\font
npm install
npm run dev -- --host 127.0.0.1 --port 5173 --strictPort
```

打开 http://127.0.0.1:5173 。后端默认地址为 http://127.0.0.1:8000 ，可在“连接设置”修改。前端直接调用后端，不添加 `/api` 前缀。5173 是后端默认 CORS 允许的端口；其他端口需在后端配置 `CORS_ORIGINS` 并重启。

后端在仓库根目录通过 `.venv/Scripts/python.exe -m rag_service.api` 启动，数据库等依赖按后端文档准备。review 模式需要后端启用 `LOCAL_REVIEW=true`，它不是登录权限。

## 测试顺序

1. 点击右上角连接状态执行健康检查（仅检查 SQL/Milvus）。
2. PDF 导入：选文件与结束页，上传并等待 OCR；只有 `manifest.status=completed` 才能确认入库。入库需要手动点击，不会自动调用或定时重试。
3. 检索测试：输入 query、limit 和 review；检索结果可打开详情。新入库题目尚未发布，普通模式可能看不到。
4. 题目详情：输入完整 question_id，可查看图片、原文以及解析后的 JSON 响应。

上传等待最长 31 分钟；入库等待最长 10 分钟；检索与详情等待最长 45 秒。超时不代表服务端停止，避免盲目重复提交。任务 `pending/running` 不显示成功，也不自动重复 POST。

“原始响应”面板展示 JSON.parse 后的数据，非精确原始字节；question_version 可能超过 JavaScript 安全整数，不用于精确比较。排名融合分不显示为百分比。界面不提供未实现的判题、发布或聊天功能。

## 验证与结构

```powershell
npm test
npm run build
```

- `src/App.vue`：导航、后端地址与健康检查。
- `src/views/`：导入、检索和详情，按业务页面拆分。
- `src/lib/api.ts`：类型、HTTP、文件上传和接口约束。
- `src/components/`：图标、题目卡片和响应检查。
- `src/style.css`：浅灰白背景、白卡片、蓝色主色以及响应式布局。

测试使用受控请求，不会调用真实 OCR 或写入数据库。构建与辅助逻辑测试通过不代表真实后端端到端流程已通过。
