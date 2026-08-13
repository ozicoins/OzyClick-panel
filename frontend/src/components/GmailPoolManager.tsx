import { useState, useRef } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { Users, UserPlus, Trash2, X, Eye, EyeOff, Upload, ListPlus, RefreshCw, AlertTriangle } from 'lucide-react'
import toast from 'react-hot-toast'
import { api } from '../api/client'
import type { GmailAccount } from '../types'
import GlassCard from './ui/GlassCard'
import PanelHeader from './ui/PanelHeader'
import EmptyState from './ui/EmptyState'

interface Props {
  accounts: GmailAccount[]
  activeEmail: string
  onSelectEmail: (email: string) => void
  onAccountsChanged?: (accounts: GmailAccount[]) => void
}

const BULK_PLACEHOLDER = `Her satır bir hesap:
ali@gmail.com|Sifre123|JBSWY3DPEHPK3PXP|yedek@gmail.com|1.2.3.4:8080:kadi:kpar
veli@gmail.com|Sifre456|JBSWY3DPEHPK3PXP||1.2.3.4:8080
can@gmail.com|Sifre789`

export default function GmailPoolManager({ accounts, activeEmail, onSelectEmail, onAccountsChanged }: Props) {
  const [showManual, setShowManual] = useState(false)
  const [bulk, setBulk] = useState('')
  const [form, setForm] = useState({ email: '', password: '', totp_secret: '', proxy_ip: '', recovery_email: '' })
  const [useRecovery, setUseRecovery] = useState(false)
  const [revealed, setRevealed] = useState<Record<string, { password: string; totp_secret: string; proxy_ip: string }>>({})
  const fileRef = useRef<HTMLInputElement>(null)

  // Cihaz-onaylı 2FA (otomatikleşmez) hesaplar + günlük üretim sayacı
  const { data: flags } = useQuery({
    queryKey: ['account-flags'],
    queryFn: () => api.getAccountFlags(),
    refetchInterval: 20_000,
  })
  const devicePrompt = new Set(flags?.device_prompt ?? [])
  const dailyLimit = flags?.daily_limit ?? 0

  const toggleReveal = async (email: string) => {
    if (revealed[email] !== undefined) {
      setRevealed(r => { const n = { ...r }; delete n[email]; return n })
      return
    }
    try {
      const c = await api.revealAccount(email)
      setRevealed(r => ({ ...r, [email]: { password: c.password, totp_secret: c.totp_secret, proxy_ip: c.proxy_ip } }))
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Bilgiler gösterilemedi')
    }
  }

  // Toplu ekle (yapıştır) — ANA yol.
  const bulkMut = useMutation({
    mutationFn: () => api.addAccountsBulk(bulk),
    onSuccess: (res) => {
      onAccountsChanged?.(res.accounts)
      if (res.accounts.length) onSelectEmail(res.accounts[0].email)
      setBulk('')
      toast.success(res.message)
    },
    onError: (e: Error) => toast.error(e.message),
  })

  // Dosya yükle (.txt/.csv) — aynı formatı kabul eder.
  const uploadMut = useMutation({
    mutationFn: (file: File) => api.uploadCsv(file),
    onSuccess: (res) => {
      onAccountsChanged?.(res.accounts)
      if (res.accounts.length) onSelectEmail(res.accounts[0].email)
      toast.success(res.message)
    },
    onError: (e: Error) => toast.error(e.message),
  })

  // Manuel tek ekle (opsiyonel).
  const addMut = useMutation({
    mutationFn: () => api.addAccount({
      email: form.email.trim(), password: form.password,
      totp_secret: form.totp_secret.trim() || undefined,
      proxy_ip: form.proxy_ip.trim() || undefined,
      recovery_email: useRecovery ? (form.recovery_email.trim() || undefined) : undefined,
    }),
    onSuccess: (res) => {
      onAccountsChanged?.(res.accounts)
      if (form.email.trim()) onSelectEmail(form.email.trim())
      setForm({ email: '', password: '', totp_secret: '', proxy_ip: '', recovery_email: '' })
      setUseRecovery(false)
      setShowManual(false)
      toast.success(res.message)
    },
    onError: (e: Error) => toast.error(e.message),
  })

  const removeMut = useMutation({
    mutationFn: (email: string) => api.removeAccount(email),
    onSuccess: (res) => { onAccountsChanged?.(res.accounts); toast.success('Hesap silindi') },
    onError: (e: Error) => toast.error(e.message),
  })

  const canAdd = form.email.trim().includes('@') && form.password.length > 0

  return (
    <GlassCard className="space-y-3">
      <PanelHeader
        icon={Users}
        title={`Hesap Havuzu${accounts.length ? ` (${accounts.length})` : ''}`}
        actions={
          <button onClick={() => setShowManual(v => !v)} aria-label="Tek hesap ekle" title="Tek tek ekle"
            className={`p-1 rounded-lg transition-colors ${showManual ? 'text-iuGold bg-iuGold/10' : 'text-slate-500 hover:text-iuGold hover:bg-iuGold/10'}`}>
            {showManual ? <X className="w-3.5 h-3.5" /> : <UserPlus className="w-3.5 h-3.5" />}
          </button>
        }
      />

      {/* TOPLU EKLE — ana yol (TOTP + kurtarma + proxy tek satırda) */}
      <div className="space-y-1.5">
        <textarea
          value={bulk}
          onChange={e => setBulk(e.target.value)}
          rows={4}
          spellCheck={false}
          placeholder={BULK_PLACEHOLDER}
          className="w-full bg-iuNavy/50 border border-iuBorder rounded-lg px-3 py-2 text-[11px] font-mono text-slate-300 placeholder-slate-600 focus:border-iuGold focus:outline-none resize-y"
        />
        <p className="text-[10px] text-slate-600 leading-snug">
          Sıra: <span className="text-iuGold font-mono">email · parola · totp · kurtarma · proxy</span>.
          Ayraç <b className="text-slate-400">fark etmez</b> — <span className="font-mono">|</span> , boşluk <span className="font-mono">;</span> <span className="font-mono">:</span> hepsi olur.
          totp/kurtarma/proxy opsiyonel; sadece <span className="font-mono">email parola</span> de yeter. proxy = <span className="font-mono">host:port</span> veya <span className="font-mono">host:port:kadı:kpar</span>.
        </p>
        <div className="flex gap-2">
          <button
            onClick={() => bulkMut.mutate()}
            disabled={!bulk.trim() || bulkMut.isPending}
            className="flex-1 py-1.5 rounded-lg bg-iuGold text-iuNavy font-medium text-xs hover:bg-iuGoldHover disabled:opacity-40 transition-all flex items-center justify-center gap-1.5"
          >
            <ListPlus className="w-3.5 h-3.5" /> {bulkMut.isPending ? 'Ekleniyor...' : 'Toplu Ekle'}
          </button>
          <button
            onClick={() => fileRef.current?.click()}
            disabled={uploadMut.isPending}
            title=".txt / .csv dosyası yükle (aynı format)"
            className="px-3 py-1.5 rounded-lg bg-iuNavy/50 text-slate-400 border border-iuBorder hover:text-iuGold disabled:opacity-40 text-xs flex items-center gap-1.5 transition-colors"
          >
            <Upload className="w-3.5 h-3.5" /> {uploadMut.isPending ? '...' : 'Dosya'}
          </button>
          <input
            ref={fileRef}
            type="file"
            accept=".txt,.csv"
            className="hidden"
            onChange={e => { const f = e.target.files?.[0]; if (f) uploadMut.mutate(f); e.target.value = '' }}
          />
        </div>
      </div>

      {/* MANUEL TEK EKLE — opsiyonel, + ile açılır */}
      {showManual && (
        <div className="space-y-2 bg-iuNavy/30 rounded-lg p-2.5 border border-iuBorder">
          <p className="text-[10px] text-slate-500">Tek hesap ekle</p>
          <input value={form.email} onChange={e => setForm(f => ({ ...f, email: e.target.value }))} placeholder="email@gmail.com" autoComplete="off"
            className="w-full bg-iuNavy/50 border border-iuBorder rounded-lg px-3 py-1.5 text-xs text-slate-300 placeholder-slate-600 focus:border-iuGold focus:outline-none" />
          <input type="password" value={form.password} onChange={e => setForm(f => ({ ...f, password: e.target.value }))} placeholder="şifre" autoComplete="off"
            className="w-full bg-iuNavy/50 border border-iuBorder rounded-lg px-3 py-1.5 text-xs text-slate-300 placeholder-slate-600 focus:border-iuGold focus:outline-none" />
          <div className="grid grid-cols-2 gap-2">
            <input value={form.totp_secret} onChange={e => setForm(f => ({ ...f, totp_secret: e.target.value }))} placeholder="2FA secret (ops.)" autoComplete="off"
              className="bg-iuNavy/50 border border-iuBorder rounded-lg px-3 py-1.5 text-xs text-slate-300 placeholder-slate-600 focus:border-iuGold focus:outline-none" />
            <input value={form.proxy_ip} onChange={e => setForm(f => ({ ...f, proxy_ip: e.target.value }))} placeholder="proxy (ops.)" autoComplete="off"
              className="bg-iuNavy/50 border border-iuBorder rounded-lg px-3 py-1.5 text-xs text-slate-300 placeholder-slate-600 focus:border-iuGold focus:outline-none" />
          </div>
          <label className="flex items-center gap-2 text-[11px] text-slate-400 cursor-pointer select-none">
            <input type="checkbox" checked={useRecovery} onChange={e => setUseRecovery(e.target.checked)} className="accent-iuGold w-3.5 h-3.5" />
            Kurtarma e-postası ile doğrula (2FA yok, "kurtarma adresini onayla" çıkan hesaplar)
          </label>
          {useRecovery && (
            <input value={form.recovery_email} onChange={e => setForm(f => ({ ...f, recovery_email: e.target.value }))}
              placeholder="kurtarma e-postası (ör. yedek@gmail.com)" autoComplete="off"
              className="w-full bg-iuNavy/50 border border-iuGold/30 rounded-lg px-3 py-1.5 text-xs text-slate-300 placeholder-slate-600 focus:border-iuGold focus:outline-none" />
          )}
          <button onClick={() => addMut.mutate()} disabled={!canAdd || addMut.isPending}
            className="w-full py-1.5 rounded-lg bg-iuGold text-iuNavy font-medium text-xs hover:bg-iuGoldHover disabled:opacity-40 transition-all">
            {addMut.isPending ? 'Ekleniyor...' : 'Hesabı Ekle'}
          </button>
        </div>
      )}

      {/* LİSTE */}
      {accounts.length === 0 ? (
        <EmptyState icon={Users} message="Yukarıya hesapları yapıştırıp 'Toplu Ekle'ye basın" />
      ) : (
        <div className="space-y-1.5 max-h-40 overflow-y-auto" role="listbox" aria-label="Gmail hesapları">
          {accounts.map((acc, i) => {
            const selected = activeEmail === acc.email
            const rev = revealed[acc.email]
            return (
              <div key={acc.email || i} className={`rounded-lg transition-all ${selected ? 'bg-iuGold/10 border border-iuGold/30' : 'hover:bg-white/[0.02] border border-transparent'}`}>
                <div className="w-full flex items-center gap-2 px-3 py-2">
                  <button role="option" aria-selected={selected} onClick={() => onSelectEmail(acc.email)} className="flex items-center gap-3 flex-1 min-w-0 text-left">
                    <div className={`w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold flex-shrink-0 ${selected ? 'bg-iuGold text-iuNavy' : 'bg-iuNavy/80 text-slate-400'}`}>
                      {acc.email?.[0]?.toUpperCase() ?? '?'}
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="text-xs text-slate-300 truncate flex items-center gap-1">
                        {acc.email}
                        {devicePrompt.has(acc.email) && (
                          <AlertTriangle className="w-3 h-3 text-amber-400 flex-shrink-0" aria-label="Cihaz-onaylı 2FA — otomatikleşmez" />
                        )}
                      </p>
                      <p className="text-[10px] text-slate-600 truncate">
                        {acc.proxy_ip ? 'proxy ✓' : 'proxy yok'}
                        {flags?.daily?.[acc.email] ? ` · bugün ${flags.daily[acc.email]}${dailyLimit ? '/' + dailyLimit : ''}` : ''}
                        {devicePrompt.has(acc.email) && <span className="text-amber-400"> · cihaz-onaylı 2FA (sil)</span>}
                      </p>
                    </div>
                  </button>
                  <button onClick={() => toggleReveal(acc.email)} aria-label={`${acc.email} bilgilerini göster`} title="Bilgileri göster"
                    className={`p-1 rounded flex-shrink-0 ${rev ? 'text-iuGold' : 'text-slate-600 hover:text-iuGold'}`}>
                    {rev ? <EyeOff className="w-3.5 h-3.5" /> : <Eye className="w-3.5 h-3.5" />}
                  </button>
                  <button onClick={() => removeMut.mutate(acc.email)} disabled={removeMut.isPending} aria-label={`${acc.email} sil`} title="Sil"
                    className="p-1 rounded text-slate-600 hover:text-red-400 flex-shrink-0">
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                </div>
                {rev && (
                  <div className="px-3 pb-2 -mt-1 text-[10px] font-mono text-slate-400 space-y-0.5 break-all">
                    <p>şifre: <span className="text-emerald-400">{rev.password || '-'}</span></p>
                    <p>2fa: <span className="text-emerald-400">{rev.totp_secret || '-'}</span></p>
                    <p>proxy: <span className="text-emerald-400">{rev.proxy_ip || '-'}</span></p>
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}

      <div className="flex gap-2 text-[10px]">
        <span className="flex items-center gap-1 text-slate-500"><RefreshCw className="w-3 h-3" aria-hidden="true" /> Round-robin rotasyon · dedup (aynı e-posta bir kez)</span>
      </div>
    </GlassCard>
  )
}
