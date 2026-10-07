import { describe, expect, test } from 'bun:test'
import { GATEWAY_STORAGE_KEY, resolveGatewayUrl } from './agentConfig'

function memoryStorage(initial: Record<string, string> = {}) {
  const data = new Map(Object.entries(initial))
  return {
    getItem: (k: string) => data.get(k) ?? null,
    setItem: (k: string, v: string) => void data.set(k, v),
    removeItem: (k: string) => void data.delete(k),
    data,
  }
}

describe('resolveGatewayUrl', () => {
  test('uses the build-time URL without a parameter', () => {
    expect(resolveGatewayUrl('http://127.0.0.1:9700/', '', memoryStorage())).toBe('http://127.0.0.1:9700')
  })

  test('a ?gateway= parameter wins and is remembered', () => {
    const s = memoryStorage()
    expect(resolveGatewayUrl('', '?gateway=https://abc.trycloudflare.com/', s)).toBe('https://abc.trycloudflare.com')
    expect(s.data.get(GATEWAY_STORAGE_KEY)).toBe('https://abc.trycloudflare.com')
    expect(resolveGatewayUrl('', '', s)).toBe('https://abc.trycloudflare.com')
  })

  test('an empty ?gateway= forgets the remembered URL', () => {
    const s = memoryStorage({ [GATEWAY_STORAGE_KEY]: 'https://old.trycloudflare.com' })
    expect(resolveGatewayUrl('http://127.0.0.1:9700', '?gateway=', s)).toBe('http://127.0.0.1:9700')
    expect(s.data.has(GATEWAY_STORAGE_KEY)).toBe(false)
  })

  test('a value that is not an http(s) URL is ignored', () => {
    const s = memoryStorage()
    expect(resolveGatewayUrl('http://127.0.0.1:9700', '?gateway=javascript:alert(1)', s)).toBe('http://127.0.0.1:9700')
    expect(s.data.size).toBe(0)
  })

  test('works when storage throws (private window)', () => {
    const throwing = {
      getItem: () => { throw new Error('blocked') },
      setItem: () => { throw new Error('blocked') },
      removeItem: () => { throw new Error('blocked') },
    }
    expect(resolveGatewayUrl('', '?gateway=https://abc.trycloudflare.com', throwing)).toBe('https://abc.trycloudflare.com')
    expect(resolveGatewayUrl('http://127.0.0.1:9700', '', throwing)).toBe('http://127.0.0.1:9700')
  })
})
