import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  ApiError,
  clearAccessKey,
  getAccessKey,
  getMetrics,
  setAccessKey,
} from '../src/services/api'

const sessionValues = new Map()
global.sessionStorage = {
  getItem: (key) => sessionValues.get(key) || null,
  setItem: (key, value) => sessionValues.set(key, value),
  removeItem: (key) => sessionValues.delete(key),
}

afterEach(() => {
  clearAccessKey()
  sessionValues.clear()
  vi.restoreAllMocks()
})

describe('document API errors', () => {
  it('loads the exact metrics route', async () => {
    const payload = { success: true, data: { total: 0 } }
    global.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(payload), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }),
    )

    await expect(getMetrics()).resolves.toEqual(payload)
    expect(global.fetch).toHaveBeenCalledWith('/api/documents/metrics/summary', expect.any(Object))
  })

  it.each([
    [401, 'A valid document access key is required'],
    [413, 'File exceeds the configured limit'],
    [422, 'Validation error'],
  ])('shows the safe API message for status %s', async (status, message) => {
    global.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ success: false, message }), {
        status,
        headers: { 'content-type': 'application/json' },
      }),
    )

    try {
      await getMetrics()
      throw new Error('Expected getMetrics to reject')
    } catch (error) {
      expect(error).toBeInstanceOf(ApiError)
      expect(error.status).toBe(status)
      expect(error.message).toBe(message)
    }
  })

  it('keeps the operator key in session storage and sends it as a request header', async () => {
    setAccessKey('session-only-key')
    global.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ success: true, data: { total: 0 } }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }),
    )

    await getMetrics()

    expect(getAccessKey()).toBe('session-only-key')
    const requestOptions = global.fetch.mock.calls[0][1]
    expect(requestOptions.headers.get('X-DocFlow-Key')).toBe('session-only-key')
  })

  it('does not send an access header before the operator enters a key', async () => {
    global.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ success: true, data: { total: 0 } }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }),
    )

    await getMetrics()

    const requestOptions = global.fetch.mock.calls[0][1]
    expect(requestOptions.headers.has('X-DocFlow-Key')).toBe(false)
  })
})
