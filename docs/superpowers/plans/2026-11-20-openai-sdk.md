# OpenAI SDK migration

用户指定切换到 OpenAI SDK 和工作空间 compatible-mode/v1 地址。

- [x] 修改测试为兼容协议，验证旧实现失败。
- [x] OCRClient 使用 chat.completions.create；保持布局校验和单一重试预算。
- [x] CLI 管理 SDK 生命周期；迁移 .env、示例及默认地址，保留密钥。
- [x] 更新说明；21 项测试通过。分页与 Markdown 代码未变。
- [x] 合成扫描 PDF 真实接口成功，断言文字与插图顺序及 PNG Base64 解码通过。
