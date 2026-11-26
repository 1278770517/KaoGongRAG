# PDF 上传与 Markdown 入库

前端联调以 [前端接口契约](frontend-api-contract.md) 为依据，包含全部现有接口、响应字段和错误处理约定。

启动：`.venv/Scripts/python.exe -m rag_service.api`。本机接口，尚无公网鉴权；默认监听127.0.0.1:8000。

## 1. POST /imports/pdf?end_page=10

支持 multipart/form-data 的 `file` 字段，或 application/pdf 原始请求体。

```powershell
curl.exe -X POST "http://127.0.0.1:8000/imports/pdf?end_page=10" -F "file=@2023公考公基常识必刷600题-解析册_第2-100页.pdf"
```

默认前10页，可指定end_page，始终从第1页开始。调用现有 pdf_ocr.async_converter.convert_pdf_async，不修改其实现。
每次生成独立 output/<uuid>/upload 目录，避免文件名冲突。响应含directory、markdown_paths及manifest；需检查manifest.status，partial_failure不是全部成功。
OCR接口直接等待完成，最长30分钟；客户端/反向代理需要足够长超时。单进程一次一个OCR任务，页并发读取现有OCR配置；文件上限100MiB（multipart解析可能先落临时文件）。

## 2. POST /imports/markdown

```json
{"path":"D:/KaoGongRAG/output/<uuid>/upload","retry_failed":false}
```

path可为第一步directory，也可为该目录下某一页的.md路径。传单页路径仍导入该manifest的完整页范围，保留跨页题目上下文。
只允许项目output下的OCR产物；要求manifest、layout.json、page.png等关联文件，暂不支持脱离OCR目录的任意Markdown。
正文以MD为准；layout用于图片顺序与坐标，图片数量不一致拒绝入库。保留文档前言，清除索引中的页脚宣传信息。

响应包括job_id、status、parents、chunks、assets。仅status=completed表示验证完成；运行中的重复请求可能返回running。已完成重复请求复用任务；failed可设置retry_failed=true重新尝试。
只领取当前请求对应任务，不会触发其他待处理导入。索引耗时上限240秒，失败保留任务记录。
数据存入现有PostgreSQL父题/资源表与kaogong_service_v1集合；仍保留审核状态。测试检索需LOCAL_REVIEW=true和review=true。

## 当前边界

依然使用现有选择题解析规则，超长块明确拒绝，未承诺任意PDF题型。MD图片使用OCR原始页图裁剪；修改内嵌图片本身不属于支持范围。
没有新增缓存、常驻任务队列或云部署。OCR中断后的目录保留用于排查，重传生成新目录，不自动续跑。
