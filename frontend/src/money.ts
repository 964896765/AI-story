/** Parse decimal currency units without rounding through binary floating point. */
export function toMicros(value: string): number {
  if (!/^\d{1,10}(\.\d{1,6})?$/.test(value.trim())) throw new Error('金额须为非负数，最多六位小数')
  const [whole = '0', fraction = ''] = value.trim().split('.')
  const micros = BigInt(whole) * 1_000_000n + BigInt(fraction.padEnd(6, '0'))
  if (micros > BigInt(Number.MAX_SAFE_INTEGER)) throw new Error('金额超出安全范围')
  return Number(micros)
}
