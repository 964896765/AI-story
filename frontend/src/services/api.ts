export async function api<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch('/api' + path, options)
  const data = await response.json().catch(() => null)
  if (!response.ok) {
    const detail: unknown = data?.detail
    throw new Error(typeof detail === 'string' ? detail : detail ? JSON.stringify(detail) : `请求失败（HTTP ${response.status}）`)
  }
  return data as T
}

export function post<T>(path: string, payload?: object) {
  return api<T>(path, payload ? {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
  } : { method: 'POST' })
}
