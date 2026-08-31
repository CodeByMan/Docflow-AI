const API_BASE = (import.meta.env.VITE_API_BASE_URL || '/api').replace(/\/$/, '')
const ACCESS_KEY_STORAGE = 'docflow-access-key'

export class ApiError extends Error {
  constructor(message, status = 0, details = null) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.details = details
  }
}

function sessionStore() {
  return typeof globalThis.sessionStorage === 'undefined' ? null : globalThis.sessionStorage
}

export function getAccessKey() {
  return sessionStore()?.getItem(ACCESS_KEY_STORAGE) || ''
}

export function hasAccessKey() {
  return Boolean(getAccessKey())
}

export function setAccessKey(value) {
  const key = value.trim()
  if (!key) {
    clearAccessKey()
    return
  }
  sessionStore()?.setItem(ACCESS_KEY_STORAGE, key)
}

export function clearAccessKey() {
  sessionStore()?.removeItem(ACCESS_KEY_STORAGE)
}

function authorizedHeaders(initialHeaders = {}) {
  const headers = new Headers(initialHeaders)
  const accessKey = getAccessKey()
  if (accessKey) headers.set('X-DocFlow-Key', accessKey)
  return headers
}

async function request(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: authorizedHeaders(options.headers),
  })
  const contentType = response.headers.get('content-type') || ''
  const payload = contentType.includes('application/json') ? await response.json() : null

  if (!response.ok) {
    throw new ApiError(
      payload?.message || `Request failed with status ${response.status}`,
      response.status,
      payload?.data || null,
    )
  }
  return payload
}

export function healthCheck() {
  return request('/health/ready')
}

export function getMetrics() {
  return request('/documents/metrics/summary')
}

export function listDocuments(limit = 30) {
  return request(`/documents?limit=${limit}`)
}

export function getDocument(jobId) {
  return request(`/documents/${encodeURIComponent(jobId)}`)
}

export function processDocument(jobId) {
  return request(`/documents/${encodeURIComponent(jobId)}/process`, { method: 'POST' })
}

export async function downloadDocument(jobId) {
  const response = await fetch(`${API_BASE}/documents/${encodeURIComponent(jobId)}/download`, {
    headers: authorizedHeaders(),
  })
  if (!response.ok) {
    const payload = (response.headers.get('content-type') || '').includes('application/json')
      ? await response.json()
      : null
    throw new ApiError(payload?.message || 'Unable to download the source document', response.status)
  }
  return response.blob()
}

export function uploadDocument({ file, documentType = 'auto', autoProcess = true, onProgress }) {
  const form = new FormData()
  form.append('file', file)
  form.append('document_type', documentType)
  form.append('auto_process', String(autoProcess))

  // XMLHttpRequest is used only here so upload progress can be displayed.
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open('POST', `${API_BASE}/documents/upload`)
    xhr.responseType = 'json'
    const accessKey = getAccessKey()
    if (accessKey) xhr.setRequestHeader('X-DocFlow-Key', accessKey)

    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable && onProgress) {
        onProgress(Math.round((event.loaded / event.total) * 100))
      }
    }
    xhr.onerror = () => reject(new ApiError('Network error while uploading the document'))
    xhr.onload = () => {
      const payload = xhr.response
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(payload)
      } else {
        reject(new ApiError(payload?.message || 'Upload failed', xhr.status, payload?.data))
      }
    }
    xhr.send(form)
  })
}
