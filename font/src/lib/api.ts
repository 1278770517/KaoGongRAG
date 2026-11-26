export interface Question {
  question_id: string
  question_text?: string
  number?: number
  options?: Record<string, string>
  source_pages?: number[]
  image_urls?: string[]
  score?: number
  answer?: string | null
  raw_text?: string
  status?: string
  [key: string]: unknown
}
export interface OcrResult {
  directory: string
  markdown_paths: string[]
  manifest: { status: string; total_pages?: number; pages: { page: number; status: string; error?: string }[] }
}
export interface ImportResult {
  job_id: string; status: string; error?: string | null; parents?: number; chunks?: number; assets?: number
}
export interface SearchResult { results: Question[]; degraded: string[] }
export class ApiError extends Error {
  status: number
  body: unknown
  constructor(message: string, status: number, body: unknown) { super(message); this.status = status; this.body = body }
}
export function normalizeOrigin(value: string): string {
  const url = new URL(value.trim())
  if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password || url.search || url.hash || url.pathname !== '/') {
    throw new Error('请输入不含路径、账号和查询参数的 HTTP(S) 后端地址')
  }
  return url.origin
}
export function assetUrl(path: string, origin: string): string {
  const url = new URL(path, origin)
  if (url.origin !== new URL(origin).origin || !url.pathname.startsWith('/assets/')) throw new Error('图片地址不属于当前后端 assets 接口')
  return url.href
}
export function parseBody(text: string): unknown { try { return JSON.parse(text) } catch { return text } }
export function errorText(body: unknown): string {
  const detail = body && typeof body === 'object' && 'detail' in body ? body.detail : body
  return typeof detail === 'string' ? detail : JSON.stringify(detail, null, 2) || '未知错误'
}
export function canIndex(result: OcrResult | null): boolean { return result?.manifest.status === 'completed' && Boolean(result.directory) }
export function missingOptions(question: Question): [string, string][] {
  return Object.entries(question.options ?? {}).filter(([, value]) => !question.question_text?.includes(value))
}
export async function request<T>(origin: string, path: string, body?: unknown, timeout = 45000): Promise<T> {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeout)
  try {
    const response = await fetch(new URL(path, origin), {
      method: body === undefined ? 'GET' : 'POST',
      headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body), signal: controller.signal,
    })
    const payload = parseBody(await response.text())
    if (!response.ok) throw new ApiError(errorText(payload), response.status, payload)
    return payload as T
  } catch (error) {
    if (controller.signal.aborted) throw new Error('请求等待超时；服务端可能仍在处理，请勿立即重复提交。')
    if (error instanceof TypeError) throw new Error('无法连接后端，请检查地址、服务状态和 CORS 配置。')
    throw error
  } finally { clearTimeout(timer) }
}
export function uploadPdf(origin: string, file: File, endPage: number, onProgress: (loaded: boolean) => void): Promise<OcrResult> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open('POST', new URL(`/imports/pdf?end_page=${endPage}`, origin))
    xhr.timeout = 1_860_000
    xhr.upload.onload = () => onProgress(true)
    xhr.onerror = () => reject(new Error('上传连接失败，请检查后端与 CORS；服务端可能已收到文件。'))
    xhr.ontimeout = () => reject(new Error('OCR 等待超时；服务端可能仍在处理，请勿立即重复上传。'))
    xhr.onload = () => {
      const body = parseBody(xhr.responseText)
      if (xhr.status >= 200 && xhr.status < 300) resolve(body as OcrResult)
      else reject(new ApiError(errorText(body), xhr.status, body))
    }
    const form = new FormData()
    form.append('file', file)
    xhr.send(form)
  })
}
