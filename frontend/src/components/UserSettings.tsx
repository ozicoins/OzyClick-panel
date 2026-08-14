import { useState, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Send, KeyRound, Bell, ShieldCheck } from 'lucide-react'
import toast from 'react-hot-toast'
import { api } from '../api/client'
import type { TelegramSettings, TelegramEventFlags, CaptchaSettings } from '../types'
import GlassCard from './ui/GlassCard'
import PanelHeader from './ui/PanelHeader'

const EVENT_LABELS: { key: keyof TelegramEventFlags; label: string }[] = [
  { key: 'batch_done', label: 'Üretim bitti' },
  { key: 'backup_done', label: 'Yedek alındı' },
  { key: 'liveness_alert', label: 'Canlılık düştü' },
  { key: 'daily_summary', label: 'Günlük özet' },
]

export default function UserSettings() {
  const qc = useQueryClient()
  // --- Telegram ---
  const { data: tg } = useQuery<TelegramSettings>({ queryKey: ['telegram-settings'], queryFn: () => api.getTelegram() })
  const [botToken, setBotToken] = useState('')
  const [chatId, setChatId] = useState('')
  const [enabled, setEnabled] = useState(false)
  const [events, setEvents] = useState<TelegramEventFlags>({ batch_done: true, backup_done: true, liveness_alert: true, daily_summary: true })
  const [threshold, setThreshold] = useState(80)
  useEffect(() => {
    if (tg) {
      setChatId(tg.chat_id || '')
      setEnabled(!!tg.enabled)
      if (tg.events) setEvents(tg.events)
      if (typeof tg.liveness_threshold === 'number') setThreshold(tg.liveness_threshold)
    }
  }, [tg])

  const saveTg = useMutation({
    mutationFn: () => api.setTelegram({ bot_token: botToken, chat_id: chatId, enabled, events, liveness_threshold: threshold }),
    onSuccess: (d) => {
      qc.setQueryData(['telegram-settings'], d)   // modal + ana sayfa göstergesi anında güncellensin
      toast.success('Telegram ayarı kaydedildi')
      setBotToken('')
    },
    onError: () => toast.error('Kaydedilemedi'),
  })
  const testTg = useMutation({
    mutationFn: () => api.testTelegram(),
    onSuccess: (r) => (r.ok ? toast.success(r.detail) : toast.error(r.detail)),
    onError: () => toast.error('Test gönderilemedi'),
  })

  // --- Captcha (2captcha) ---
  const { data: cap } = useQuery<CaptchaSettings>({ queryKey: ['captcha-settings'], queryFn: () => api.getCaptcha() })
  const [capKey, setCapKey] = useState('')
  const [capEnabled, setCapEnabled] = useState(false)
  useEffect(() => { if (cap) setCapEnabled(!!cap.enabled) }, [cap])
  const saveCap = useMutation({
    mutationFn: () => api.setCaptcha({ api_key: capKey, enabled: capEnabled, service: 'capsolver' }),
    onSuccess: (d) => {
      qc.setQueryData(['captcha-settings'], d)
      toast.success('Captcha ayarı kaydedildi')
      setCapKey('')
    },
    onError: () => toast.error('Kaydedilemedi'),
  })
  const testCap = useMutation({
    mutationFn: () => api.testCaptcha(),
    onSuccess: (r) => (r.ok ? toast.success(r.detail) : toast.error(r.detail)),
    onError: () => toast.error('Sorgulanamadı'),
  })

  // --- Şifre ---
  const [curPw, setCurPw] = useState('')
  const [newPw, setNewPw] = useState('')
  const changePw = useMutation({
    mutationFn: () => api.changePassword({ current_password: curPw, new_password: newPw }),
    onSuccess: (r) => { toast.success(r.detail); setCurPw(''); setNewPw('') },
    onError: (e: any) => toast.error(e?.message || 'Şifre değiştirilemedi'),
  })

  const inputCls = 'w-full bg-iuNavy/50 border border-iuBorder rounded-lg px-3 py-2 text-xs text-slate-200 focus:border-iuGold focus:outline-none'

  return (
    <GlassCard className="space-y-4">
      <PanelHeader icon={KeyRound} title="Kullanıcı Ayarları" />

      {/* Telegram bildirimleri */}
      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <span className="text-xs text-slate-300 flex items-center gap-1.5"><Bell className="w-3.5 h-3.5 text-iuGold" /> Telegram Bildirimleri</span>
          <label className="flex items-center gap-1.5 text-[11px] text-slate-400 cursor-pointer">
            <input type="checkbox" checked={enabled} onChange={e => setEnabled(e.target.checked)} className="accent-iuGold" />
            Açık
          </label>
        </div>
        <input type="password" value={botToken} onChange={e => setBotToken(e.target.value)}
          placeholder={tg?.configured ? `Kayıtlı: ${tg.bot_token} (değiştirmek için yeni token gir)` : 'Bot token (BotFather → /newbot)'}
          className={inputCls} autoComplete="off" />
        <input value={chatId} onChange={e => setChatId(e.target.value)}
          placeholder="Chat ID (@userinfobot ile öğren)" className={inputCls} autoComplete="off" />

        {/* Hangi olaylar bildirilsin */}
        <div className="grid grid-cols-2 gap-1.5 pt-1">
          {EVENT_LABELS.map(ev => (
            <label key={ev.key} className="flex items-center gap-1.5 text-[11px] text-slate-400 cursor-pointer">
              <input type="checkbox" checked={events[ev.key]} onChange={e => setEvents(s => ({ ...s, [ev.key]: e.target.checked }))} className="accent-iuGold" />
              {ev.label}
            </label>
          ))}
        </div>
        <label className="flex items-center justify-between gap-2 text-[11px] text-slate-400">
          <span>Canlılık uyarı eşiği</span>
          <span className="flex items-center gap-1">
            <input type="number" min={0} max={100} value={threshold}
              onChange={e => setThreshold(Math.max(0, Math.min(100, Number(e.target.value) || 0)))}
              className="w-16 bg-iuNavy/50 border border-iuBorder rounded-lg px-2 py-1 text-xs text-slate-200 text-center focus:border-iuGold focus:outline-none" />
            <span className="text-slate-500">% altına düşünce uyar</span>
          </span>
        </label>

        <div className="flex gap-2">
          <button onClick={() => saveTg.mutate()} disabled={saveTg.isPending}
            className="flex-1 py-2 rounded-lg bg-iuGold/10 text-iuGold border border-iuGold/25 hover:bg-iuGold/20 disabled:opacity-40 text-xs font-medium transition-colors">
            {saveTg.isPending ? 'Kaydediliyor...' : 'Kaydet'}
          </button>
          <button onClick={() => testTg.mutate()} disabled={testTg.isPending}
            className="px-3 py-2 rounded-lg bg-iuNavy/50 text-slate-300 border border-iuBorder hover:text-iuGold disabled:opacity-40 text-xs flex items-center gap-1.5 transition-colors">
            <Send className="w-3.5 h-3.5" /> Test
          </button>
        </div>
        {/* Hazırlık durumu — neyin eksik olduğunu net söyler (kayıtlı duruma göre) */}
        {tg?.configured && (
          <p className={`text-[10px] font-medium ${!tg.chat_id || !tg.enabled ? 'text-amber-400' : 'text-emerald-400'}`}>
            {!tg.chat_id ? '⚠ chat_id eksik — gir ve Kaydet'
              : !tg.enabled ? '⚠ Kapalı — "Açık"ı işaretle ve Kaydet'
              : '✓ Hazır — bildirimler açık ve chat_id tanımlı'}
          </p>
        )}
        <p className="text-[10px] text-slate-600 leading-snug">
          Seçili olaylarda Telegram'a mesaj gelir. Token maskeli saklanır, panelde tam gösterilmez.
          <b className="text-slate-400"> chat_id</b> için: bota bir mesaj at, sonra <b className="text-slate-400">@userinfobot</b>'tan ID'ni al.
        </p>
      </div>

      <div className="h-px bg-iuBorder/60" />

      {/* Captcha (2captcha) */}
      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <span className="text-xs text-slate-300 flex items-center gap-1.5"><ShieldCheck className="w-3.5 h-3.5 text-iuGold" /> Captcha Çözücü (CapSolver)</span>
          <label className="flex items-center gap-1.5 text-[11px] text-slate-400 cursor-pointer">
            <input type="checkbox" checked={capEnabled} onChange={e => setCapEnabled(e.target.checked)} className="accent-iuGold" />
            Açık
          </label>
        </div>
        <input type="password" value={capKey} onChange={e => setCapKey(e.target.value)}
          placeholder={cap?.configured ? `Kayıtlı: ${cap.api_key} (değiştirmek için yeni anahtar gir)` : 'CapSolver API anahtarı (CAP-...)'}
          className={inputCls} autoComplete="off" />
        <div className="flex gap-2">
          <button onClick={() => saveCap.mutate()} disabled={saveCap.isPending}
            className="flex-1 py-2 rounded-lg bg-iuGold/10 text-iuGold border border-iuGold/25 hover:bg-iuGold/20 disabled:opacity-40 text-xs font-medium transition-colors">
            {saveCap.isPending ? 'Kaydediliyor...' : 'Kaydet'}
          </button>
          <button onClick={() => testCap.mutate()} disabled={testCap.isPending}
            className="px-3 py-2 rounded-lg bg-iuNavy/50 text-slate-300 border border-iuBorder hover:text-iuGold disabled:opacity-40 text-xs flex items-center gap-1.5 transition-colors">
            <ShieldCheck className="w-3.5 h-3.5" /> Bakiye
          </button>
        </div>
        {cap?.configured && (
          <p className={`text-[10px] font-medium ${!cap.enabled ? 'text-amber-400' : 'text-emerald-400'}`}>
            {!cap.enabled ? '⚠ Anahtar kayıtlı ama Kapalı — "Açık"ı işaretle ve Kaydet' : '✓ Hazır — captcha gelince otomatik çözülür'}
          </p>
        )}
        <p className="text-[10px] text-slate-600 leading-snug">
          Login'de nadiren çıkan <b className="text-slate-400">resim-captcha</b> otomatik çözülür (<b className="text-slate-400">CapSolver</b> — clicker paneliyle aynı marka, tek bakiye).
          Anahtar maskeli saklanır. Kapalıyken/anahtarsızken üretim aynen çalışır (captcha gelirse o hesap atlanır).
        </p>
      </div>

      <div className="h-px bg-iuBorder/60" />

      {/* Şifre değiştirme */}
      <div className="space-y-2">
        <span className="text-xs text-slate-300 flex items-center gap-1.5"><KeyRound className="w-3.5 h-3.5 text-iuGold" /> Panel Şifresi Değiştir</span>
        <input type="password" value={curPw} onChange={e => setCurPw(e.target.value)} placeholder="Mevcut şifre" className={inputCls} autoComplete="current-password" />
        <input type="password" value={newPw} onChange={e => setNewPw(e.target.value)} placeholder="Yeni şifre (en az 8 karakter)" className={inputCls} autoComplete="new-password" />
        <button onClick={() => changePw.mutate()} disabled={changePw.isPending || !curPw || newPw.length < 8}
          className="w-full py-2 rounded-lg bg-iuGold/10 text-iuGold border border-iuGold/25 hover:bg-iuGold/20 disabled:opacity-40 text-xs font-medium transition-colors">
          {changePw.isPending ? 'Değiştiriliyor...' : 'Şifreyi Değiştir'}
        </button>
      </div>
    </GlassCard>
  )
}
