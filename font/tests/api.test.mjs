import { test } from 'node:test'
import assert from 'node:assert/strict'
import { ApiError, assetUrl, canIndex, errorText, missingOptions, normalizeOrigin, request } from '../src/lib/api.ts'

test('only full OCR completion with directory enables indexing', () => {
  for (const status of ['partial_failure', 'failed', 'running', 'pending']) assert.equal(canIndex({ directory: 'output/x', manifest: { status } }), false)
  assert.equal(canIndex(null), false)
  assert.equal(canIndex({ directory: '', manifest: { status: 'completed' } }), false)
  assert.equal(canIndex({ directory: 'output/x', manifest: { status: 'completed' } }), true)
})
test('API origin rejects credentials, paths and non HTTP URLs', () => {
  assert.equal(normalizeOrigin(' http://localhost:8000/ '), 'http://localhost:8000')
  for (const value of ['javascript:alert(1)', 'http://localhost:8000/api', 'http://user:pass@host', 'http://host/?x=1']) assert.throws(() => normalizeOrigin(value))
})
test('assets retain review query and stay on configured backend', () => {
  assert.equal(assetUrl('/assets/abc?review=true', 'http://localhost:8000'), 'http://localhost:8000/assets/abc?review=true')
  assert.throws(() => assetUrl('https://other.test/assets/abc', 'http://localhost:8000'))
})
test('errors support string, object, validation list and non JSON body', () => {
  assert.equal(errorText({ detail: 'Local review disabled' }), 'Local review disabled')
  assert.match(errorText({ detail: { status: 'failed' } }), /failed/)
  assert.match(errorText({ detail: [{ msg: 'Invalid JSON' }] }), /Invalid JSON/)
  assert.equal(errorText('Internal Server Error'), 'Internal Server Error')
})
test('options already in question text are not repeated', () => {
  assert.deepEqual(missingOptions({ question_text: 'A. 牧野之战\nB. 官渡之战', options: { A: '牧野之战', B: '官渡之战' } }), [])
  assert.deepEqual(missingOptions({ question_text: '请选择', options: { A: '牧野之战' } }), [['A', '牧野之战']])
})
test('JSON requests serialize Windows paths and preserve structured HTTP errors', async () => {
  const original = globalThis.fetch
  try {
    let sent
    globalThis.fetch = async (url, init) => { sent = { url: String(url), ...init }; return new Response(JSON.stringify({ detail: { status: 'failed', error: 'TimeoutError' } }), { status: 503 }) }
    await assert.rejects(request('http://localhost:8000', '/imports/markdown', { path: 'D:\\output\\1', retry_failed: false }), err => err instanceof ApiError && err.status === 503 && err.body.detail.status === 'failed')
    assert.equal(JSON.parse(sent.body).path, 'D:\\output\\1')
    assert.equal(sent.method, 'POST')
    assert.equal(sent.headers['Content-Type'], 'application/json')
  } finally { globalThis.fetch = original }
})
test('request timeout reports uncertain server state instead of success', async () => {
  const original = globalThis.fetch
  try {
    globalThis.fetch = (_url, init) => new Promise((_resolve, reject) => init.signal.addEventListener('abort', () => reject(new Error('aborted'))))
    await assert.rejects(request('http://localhost:8000', '/search', {}, 5), /服务端可能仍在处理/)
  } finally { globalThis.fetch = original }
})
