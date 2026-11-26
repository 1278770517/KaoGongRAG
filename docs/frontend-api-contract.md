# 前端接口契约

更新日期：2026-11-25。依据当前 `rag_service/api.py`、`imports.py`、`retrieval.py`、`repository.py` 的实际实现。本文件描述已实现行为，不能将 PRD 中的规划接口视为可调用接口。

## 服务与接入约定

- 开发地址：`http://127.0.0.1:8000`；无额外 `/api` 前缀。
- Swagger：`/docs`；OpenAPI：`/openapi.json`。仓库快照见 `docs/openapi.snapshot.json`。
- 启动：在项目根目录运行 `.venv/Scripts/python.exe -m rag_service.api`。
- 当前无用户鉴权、分页列表、审核发布管理或 WebSocket/SSE 进度接口。
- 已配置 CORS，默认允许 `http://localhost:5173`、`http://127.0.0.1:5173`、`http://localhost:3000`、`http://127.0.0.1:3000`。允许 GET/POST 与 Content-Type/Authorization 请求头，不启用跨域 Cookie。也可使用同源开发代理。
- 自定义前端地址在后端 `.env` 配置 JSON 数组，例如 `CORS_ORIGINS=["http://localhost:5174"]`，设置后会替换默认列表；修改后需重启后端。Origin 不包含页面路径或结尾 `/`。前端无需添加任何 Access-Control-Allow-* 请求头，不使用 `credentials: "include"`。
- 本机绝对路径仅用于第二步导入参数，不是浏览器可以直接访问的资源 URL。
- 不要把数据库密码、百炼密钥或 `.env` 内容放进前端。

## 接口清单

| 方法 | 路径 | 用途 |
|---|---|---|
| POST | `/imports/pdf` | 上传 PDF，等待 OCR 完成，返回解析目录 |
| POST | `/imports/markdown` | 按解析路径分块、索引并验证 |
| POST | `/search` | dense/BM25 召回与父题排名融合 |
| GET | `/questions/{question_id}` | 按 ID 获取父题 |
| GET | `/assets/{asset_id}` | 读取关联图片 PNG |
| GET | `/health` | SQL 与 Milvus 健康检查 |

## 一、PDF 上传与 OCR

`POST /imports/pdf?end_page=10`

| 参数 | 位置 | 类型 | 约束 |
|---|---|---|---|
| end_page | query | integer | 默认 10，1—1000，必须不超过实际页数；从第 1 页开始 |
| file | multipart body | File | 恰好一个文件字段，字段名 `file` |

也接受 `Content-Type: application/pdf` 的原始字节请求体。应用层文件上限为 100 MiB。当前 OpenAPI 未声明上传 body，所以 Swagger 没有文件选择框；前端可正常用 FormData。

```javascript
const form = new FormData();
form.append('file', selectedFile);
const response = await fetch('/imports/pdf?end_page=10', {
  method: 'POST',
  body: form,
});
// 不手动设置 Content-Type，浏览器需要自动添加 multipart boundary。
```

HTTP 200 示例（pages 为逐页记录，下例为结构示意）：

```json
{
  "directory": "D:\\KaoGongRAG\\output\\<uuid>\\upload",
  "markdown_paths": ["D:\\KaoGongRAG\\output\\<uuid>\\upload\\1\\1.md"],
  "manifest": {
    "source": "upload.pdf",
    "sha256": "<PDF文件SHA256>",
    "total_pages": 49,
    "start_page": 1,
    "end_page": 10,
    "status": "completed",
    "pages": [
      {"page": 1, "status": "completed", "markdown": "1/1.md"}
    ]
  }
}
```

`manifest.pages` 实际包含每一页的记录。失败页为 `{"page":2,"status":"failed","error":"..."}`，没有 markdown 字段。`markdown_paths` 只列出成功页。

**HTTP 200 不等于全部页成功**：必须检查 `manifest.status`；只有 `completed` 才能进入第二步。`partial_failure` 应显示失败页并停止自动入库。

本接口不写 Milvus、不返回 job_id，也没有后台状态查询接口。每次上传创建独立目录，相同 PDF 再上传仍会调用 OCR。接口直接等待完成，服务端总截止时间 1800 秒（包括等待上传限流）；前端/代理需要较长超时。上传字节进度不是 OCR 页解析进度。取消浏览器请求不保证已发生的外部调用被撤销。

## 二、Markdown 路径入库

`POST /imports/markdown`，`Content-Type: application/json`。

```json
{
  "path": "D:/KaoGongRAG/output/<uuid>/upload",
  "retry_failed": false
}
```

| 字段 | 类型 | 默认/约束 |
|---|---|---|
| path | string | 必填，非空；优先直接使用 OCR 响应的 directory |
| retry_failed | boolean | 默认 false；用户明确重试失败入库时设为 true |

传入单个 `.md` 路径时仍导入该 manifest 对应的全部页，便于跨页配对，不是只导入这一页。仅支持 output 内有 manifest、layout 和相应页图的 OCR 目录，不能上传任意独立 MD 代替。路径由 JSON.stringify 序列化，避免手工拼接反斜杠导致 `Invalid \\escape`。

HTTP 200 示例：

```json
{
  "job_id": "5743224cf31c7961ac6620eefc8b056e17940bb2e6157cc5cfc1f71b324abd45",
  "status": "completed",
  "error": null,
  "parents": 25,
  "chunks": 74,
  "assets": 2
}
```

parents/chunks/assets 为本批解析的题目、分块、图片关联数量，不是 collection 总量或此次新增数量；assets 也不是保证唯一的物理文件数。

| status | 前端解释 |
|---|---|
| completed | 索引验证完成，可显示“入库成功” |
| running | 相同任务正在处理，不能显示成功 |
| pending | 已暂存，尚未完成索引 |
| failed | 已失败，可展示 error 并提供显式重试 |

同批相同内容会复用任务。可再次提交相同请求读取返回状态，但当前没有独立 GET job 状态接口；提交也可能领取 pending/过期任务并执行，不是无副作用的轮询接口。不建议前端定时反复 POST。

入库接口等待索引完成，索引阶段截止 240 秒（不包含之前的文件准备/SQL阶段）。正常新请求可能长时间等待，不能使用通常的短请求超时。失败可能 HTTP 503 返回：

```json
{"detail":{"job_id":"...","status":"failed","error":"TimeoutError"}}
```

默认写入 `kaogong_service_v1`，PDF 之间共享集合；题目仍未审核，入库完成不等于已发布。旧索引版本不是自动物理清理，检索会用父题版本校验过滤。

## 三、检索

`POST /search`，JSON：

```json
{"query":"官渡之战","limit":5,"review":true}
```

| 字段 | 类型 | 默认/约束 |
|---|---|---|
| query | string | 必填，原始长度1—2000；去除首尾空白后不能为空 |
| limit | integer | 默认10，1—50，表示最多返回的父题数 |
| review | boolean | 默认false；true需要服务端 LOCAL_REVIEW=true |

响应：

```json
{
  "results": [
    {
      "question_id": "<opaque-id>",
      "question_version": 123456,
      "number": 2,
      "question_text": "2.（单选）下图描述了……\nA. ……",
      "options": {"A":"牧野之战","B":"官渡之战","C":"赤壁之战","D":"巨鹿之战"},
      "source_pages": [1,2],
      "image_asset_ids": ["<asset-id>"],
      "image_urls": ["/assets/<asset-id>?review=true"],
      "score": 0.032
    }
  ],
  "degraded": []
}
```

普通响应字段为上例的题干白名单；review=true还会返回完整父题，包括 `answer`（string或null）、`raw_text`、`images`、`status` 等，具体取决于导入来源。解析/拓展目前存在 raw_text 中，不保证有独立 explanation 字段。question_text 当前也包含选项，前端展示时应避免与 options 重复渲染。

question_id 是不透明ID，不要用题号 number 替代。question_version 当前是JSON整数，可能超过JavaScript安全整数范围；前端不能用它做精确运算/版本判断，精确比较由后端完成，后续若需要前端精确使用应先修改后端为字符串契约。

score 为父题排名融合分，不是相似度概率/正确率，不能显示成百分比。results 已排序，可能少于limit或为空；目前无分页、总数和相似度阈值参数。dense近邻可能返回弱相关结果，非空不代表有确切答案。

degraded 中的 `dense` / `sparse` 表示对应路失败，另一条路仍正常；空数组代表没有检测到单路异常。两路都失败返回503。服务端请求截止默认30秒。

## 四、题目详情与图片

- `GET /questions/{question_id}?review=true`：返回与检索项相同的父题结构，但没有score；不调用向量检索。
- `GET /assets/{asset_id}?review=true`：成功返回 `image/png` 二进制，可直接作为 img.src。

image_urls 为相对后端地址，应相对于 API origin 拼接，或通过同源代理访问。审核模式返回的URL已带review=true，前端应保留查询参数。不要用Windows本地文件路径作为图片地址。

```javascript
const src = new URL(item.image_urls[0], apiOrigin).href;
```

review=false默认只返回已索引且published的数据；review=true可读取未审核数据。若服务端未启用LOCAL_REVIEW，检索、详情和图片均返回403。开关不是用户权限系统，前端不能将它当作登录鉴权。

## 五、健康检查及错误

`GET /health` 成功为 `{"status":"ok"}`，依赖异常503为 `{"detail":"Dependency unavailable"}`。它不检测百炼余额、OCR凭据或embedding模型可用性。

错误响应当前没有统一业务码，前端必须同时支持detail为字符串、对象、数组，以及非JSON的500响应：

| HTTP状态 | 常见含义 |
|---|---|
| 403 | `Local review disabled` |
| 404 | 题目/图片不存在或被可见性过滤 |
| 422 | 字段校验、JSON格式错误、路径越界、OCR产物不完整、图片关联不匹配或不支持的分块 |
| 503 | 检索依赖不可用、索引任务失败 |
| 504 | OCR接口总截止时间超过1800秒 |
| 500 | 未被转换的异常；需保留后端日志排查，不代表可盲目重试 |

FastAPI校验示例：`{"detail":[{"type":"json_invalid","loc":["body",15],"msg":"JSON decode error","ctx":{"error":"Invalid \\escape"}}]}`。

## 前端首期流程

选择PDF和结束页 → 上传并等待 → 校验manifest.status → 保存directory → 用户确认入库 → 提交/imports/markdown → 校验status → 搜索/查看题目 → 使用image_urls展示图片。

上传中、OCR等待、入库中、失败、部分页失败、检索降级、无结果应分别显示；没有服务端页级实时进度，不展示虚构百分比。
当前不包含随机练习、提交作答、自动判题、错题本、聊天流式回答或审核发布接口，前端不要按规划假设这些接口已存在。
