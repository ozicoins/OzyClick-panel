import { useState, useEffect, useRef, useCallback } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { getToken, getWsUrl } from '../api/client'
import type { FarmingLogEntry } from '../types'

// enabled: yalnızca kimlik doğrulandığında bağlan (login ekranında WS açılmaz;
// login sonrası bağlanır, logout'ta kapanır).
export function useFarmingLogs(enabled: boolean, maxLogs = 200) {
  const [logs, setLogs] = useState<FarmingLogEntry[]>([])
  const [connected, setConnected] = useState(false)
  const wsRef = useRef<WebSocket | null>(null)
  const retryRef = useRef(0)
  const stoppedRef = useRef(false)  // yalnızca unmount/disable'da true → süresiz reconnect
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const qc = useQueryClient()
  const lastInvalidateRef = useRef(0)   // çıktı-sayısı tazelemesini hafif throttle et
  // PERF: gelen logları tamponla, ~350ms'de bir TOPLUCA state'e yaz → Fast/Turbo'da onlarca
  // log/sn'lik sel her mesajda re-render tetiklemesin (panel kasmasının ana sebebi).
  const bufRef = useRef<FarmingLogEntry[]>([])
  const flushRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const connect = useCallback(() => {
    if (stoppedRef.current) return
    const ws = new WebSocket(getWsUrl())
    wsRef.current = ws

    ws.onopen = () => {
      // Same-origin'de auth httpOnly cookie ile otomatik. Cross-origin fallback:
      // bellekteki token varsa ilk mesaj olarak gönder (URL'de değil).
      const token = getToken()
      if (token) ws.send(JSON.stringify({ type: 'auth', token }))
      setConnected(true)
      retryRef.current = 0
    }

    ws.onmessage = (e) => {
      try {
        const entry: FarmingLogEntry = JSON.parse(e.data)
        // Tampona ekle; state flush'ı zamanlanmadıysa ~350ms sonrası için zamanla (batch re-render).
        bufRef.current.push(entry)
        if (!flushRef.current) {
          flushRef.current = setTimeout(() => {
            flushRef.current = null
            const batch = bufRef.current
            bufRef.current = []
            if (batch.length) setLogs(prev => [...prev, ...batch].slice(-maxLogs))
          }, 350)
        }
        // CANLI ÇIKTI SAYISI: ✓/[DRY] gelince "Çıktılar" havuz sayısını tazele — throttle 1.5sn
        // (Fast/Turbo'da çok sık invalidate re-fetch fırtınası yaratmasın).
        const m = entry.message || ''
        if (m.includes('✓') || m.includes('[DRY]')) {
          const now = Date.now()
          if (now - lastInvalidateRef.current > 1500) {
            lastInvalidateRef.current = now
            qc.invalidateQueries({ queryKey: ['export-stats'] })
          }
        }
      } catch { /* malformed message */ }
    }

    ws.onclose = () => {
      // Bu soket artık aktif değilse (StrictMode remount / supersede) yeniden bağlanma —
      // aksi halde eski soketin onclose'u sahte reconnect zamanlar, çift bağlantı/log olurdu.
      if (wsRef.current !== ws) return
      setConnected(false)
      if (stoppedRef.current) return
      // SÜRESİZ yeniden dene (eski hali 3 denemeden sonra kalıcı susuyordu → sunucu
      // ~14sn'den uzun düşünce loglar bir daha gelmiyordu). Üstel backoff, 30sn tavan.
      retryRef.current++
      const delay = Math.min(30000, Math.pow(2, retryRef.current) * 1000)
      timerRef.current = setTimeout(connect, delay)
    }

    ws.onerror = () => ws.close()
  }, [maxLogs, qc])

  useEffect(() => {
    if (!enabled) return
    stoppedRef.current = false
    retryRef.current = 0
    connect()
    return () => {
      stoppedRef.current = true  // temizlikte otomatik yeniden bağlanmayı durdur
      if (timerRef.current) clearTimeout(timerRef.current)  // bekleyen reconnect'i iptal et
      if (flushRef.current) { clearTimeout(flushRef.current); flushRef.current = null }
      bufRef.current = []
      wsRef.current?.close()
    }
  }, [enabled, connect])

  const clearLogs = useCallback(() => { bufRef.current = []; setLogs([]) }, [])

  return { logs, connected, clearLogs }
}
