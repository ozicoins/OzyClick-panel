import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Globe, ToggleLeft, ToggleRight, AlertTriangle, CheckCircle2, KeyRound, Plus, Trash2, RotateCw, Star, Server, Upload, Zap } from 'lucide-react'
import toast from 'react-hot-toast'
import { api } from '../api/client'
import type { ProxySettings as ProxySettingsType, ProxyQuality } from '../types'
import GlassCard from './ui/GlassCard'
import PanelHeader from './ui/PanelHeader'

const COUNTRIES: { code: string; label: string }[] = [
  { code: 'tr', label: 'Türkiye' }, { code: 'us', label: 'ABD' }, { code: 'gb', label: 'İngiltere' },
  { code: 'de', label: 'Almanya' }, { code: 'fr', label: 'Fransa' }, { code: 'nl', label: 'Hollanda' },
  { code: 'es', label: 'İspanya' }, { code: 'it', label: 'İtalya' }, { code: 'ca', label: 'Kanada' },
  { code: 'ae', label: 'BAE' },
]

const QUALITIES: { id: ProxyQuality; label: string; hint: string }[] = [
  { id: 'classic', label: 'Classic', hint: '1 kredi' },
  { id: 'premium', label: 'Premium', hint: '~10-25 kredi · residential' },
  { id: 'stealth', label: 'Stealth', hint: '~75 kredi · en güçlü' },
]

export default function ProxySettings() {
  const queryClient = useQueryClient()
  const [singleKey, setSingleKey] = useState('')
  const [bulkKeys, setBulkKeys] = useState('')
  const [showBulk, setShowBulk] = useState(false)
  const [singleProxy, setSingleProxy] = useState('')
  const [bulkProxies, setBulkProxies] = useState('')
  const [showBulkProxy, setShowBulkProxy] = useState(false)
  // Proxy canlılık testi sonuçları (index → sonuç) + o an test edilen
  const [testResults, setTestResults] = useState<Record<number, { alive: boolean; latency_ms: number; exit_ip: string; error: string }>>({})
  const [testingIdx, setTestingIdx] = useState<number | 'all' | null>(null)

  const { data } = useQuery<ProxySettingsType>({
    queryKey: ['proxy-settings'],
    queryFn: () => api.getProxySettings(),
  })

  const mutation = useMutation({
    mutationFn: (patch: Parameters<typeof api.setProxySettings>[0]) => api.setProxySettings(patch),
    onSuccess: (result) => queryClient.setQueryData(['proxy-settings'], result),
    onError: (e: Error) => toast.error(e.message),
  })

  const rotate = useMutation({
    mutationFn: () => api.rotateProxyKey(),
    onSuccess: (result) => { queryClient.setQueryData(['proxy-settings'], result); toast.success('Sonraki anahtara geçildi') },
    onError: (e: Error) => toast.error(e.message),
  })

  const testMut = useMutation({
    mutationFn: (index?: number) => api.testProxies(index),
    onSuccess: (res) => {
      setTestResults(prev => {
        const n = { ...prev }
        for (const r of res.results) n[r.index] = { alive: r.alive, latency_ms: r.latency_ms, exit_ip: r.exit_ip, error: r.error }
        return n
      })
      const ok = res.results.filter(r => r.alive).length
      toast.success(`Test: ${ok}/${res.results.length} canlı`)
    },
    onError: (e: Error) => toast.error(e.message),
  })
  const runTest = (index?: number) => {
    setTestingIdx(index === undefined ? 'all' : index)
    testMut.mutate(index, { onSettled: () => setTestingIdx(null) })
  }

  const provider = data?.provider ?? 'csv'
  const isSB = provider === 'scrapingbee'
  const isList = provider === 'list'
  const country = data?.country ?? 'tr'
  const renderJs = data?.render_js ?? false
  const quality = data?.quality ?? 'classic'
  const previews = data?.api_key_previews ?? []
  const activeIdx = data?.active_index ?? 0
  const keyCount = data?.api_key_count ?? 0
  const proxyPreviews = data?.proxy_previews ?? []
  const proxyCount = data?.proxy_count ?? 0

  const addSingle = () => {
    if (!singleKey.trim()) return
    mutation.mutate({ add_api_keys: [singleKey.trim()] }, { onSuccess: () => { setSingleKey(''); toast.success('Anahtar eklendi') } })
  }
  const addBulk = () => {
    const keys = bulkKeys.split('\n').map(k => k.trim()).filter(Boolean)
    if (!keys.length) return
    mutation.mutate({ add_api_keys: keys }, { onSuccess: () => { setBulkKeys(''); setShowBulk(false); toast.success(`${keys.length} anahtar eklendi`) } })
  }
  const addProxy = () => {
    if (!singleProxy.trim()) return
    mutation.mutate({ add_proxies: [singleProxy.trim()] }, { onSuccess: (r) => { setSingleProxy(''); toast.success(r.proxy_count > proxyCount ? 'Proxy eklendi' : 'Geçersiz format') } })
  }
  const addBulkProxies = () => {
    const list = bulkProxies.split('\n').map(k => k.trim()).filter(Boolean)
    if (!list.length) return
    mutation.mutate({ add_proxies: list }, { onSuccess: () => { setBulkProxies(''); setShowBulkProxy(false); toast.success('Proxy(ler) eklendi') } })
  }
  // .txt dosyasından toplu proxy yükle (her satır bir proxy) → mevcut add_proxies'e verir.
  const uploadProxyTxt = (file?: File) => {
    if (!file) return
    const reader = new FileReader()
    reader.onload = () => {
      const list = String(reader.result || '').split('\n').map(s => s.trim()).filter(Boolean)
      if (!list.length) { toast.error('Dosya boş'); return }
      mutation.mutate({ add_proxies: list }, {
        onSuccess: (r) => toast.success(`${list.length} satır işlendi · havuzda ${r.proxy_count} proxy`),
      })
    }
    reader.onerror = () => toast.error('Dosya okunamadı')
    reader.readAsText(file)
  }

  return (
    <GlassCard className="space-y-3">
      <PanelHeader icon={Globe} title="Proxy Ayarları" />

      <div className="grid grid-cols-3 gap-2">
        {([['csv', 'CSV'], ['list', 'Proxy Listesi'], ['scrapingbee', 'ScrapingBee']] as const).map(([p, label]) => (
          <button key={p} onClick={() => mutation.mutate({ provider: p })} aria-pressed={provider === p} disabled={mutation.isPending}
            className={`py-2 rounded-lg border text-[11px] transition-all ${provider === p ? 'border-iuGold bg-iuGold/10 text-iuGold' : 'border-iuBorder text-slate-400 hover:border-iuBorder/80'}`}>
            {label}
          </button>
        ))}
      </div>

      {provider === 'csv' && (
        <p className="text-[11px] text-slate-500 bg-iuNavy/30 rounded-lg p-2">
          Her hesabın kendi proxy'si kullanılır (hesaba eklenen <code className="text-iuGold/80">proxy</code> alanı).
        </p>
      )}

      {isList && (
        <>
          <div className={`flex items-center gap-2 rounded-lg p-2 text-[11px] ${proxyCount > 0 ? 'bg-emerald-500/5 text-emerald-400' : 'bg-amber-500/10 text-amber-400'}`}>
            <Server className="w-3.5 h-3.5" />
            {proxyCount > 0 ? `${proxyCount} proxy havuzda (round-robin)` : 'Proxy yok — aşağıdan ekleyin'}
          </div>

          {proxyCount > 0 && (
            <button onClick={() => runTest()} disabled={testMut.isPending}
              className="w-full py-1.5 rounded-lg bg-iuNavy/50 text-slate-400 border border-iuBorder hover:text-iuGold hover:border-iuGold/30 disabled:opacity-40 text-[11px] flex items-center justify-center gap-1.5 transition-colors">
              <Zap className="w-3 h-3" /> {testingIdx === 'all' && testMut.isPending ? 'Test ediliyor...' : 'Tümünü test et (canlılık)'}
            </button>
          )}

          {proxyPreviews.length > 0 && (
            <div className="space-y-1 max-h-40 overflow-y-auto">
              {proxyPreviews.map((p, i) => {
                const tr = testResults[i]
                return (
                  <div key={i} className="flex flex-col gap-0.5 px-2.5 py-1.5 rounded-lg text-[10px] border border-iuBorder bg-iuNavy/30">
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-slate-400 flex-1 truncate">#{i + 1} · {p}</span>
                      <button onClick={() => runTest(i)} disabled={testMut.isPending} className="text-slate-600 hover:text-iuGold disabled:opacity-40" aria-label="Canlılık testi" title="Canlılık testi">
                        <Zap className={`w-3 h-3 ${testingIdx === i && testMut.isPending ? 'animate-pulse text-iuGold' : ''}`} />
                      </button>
                      <button onClick={() => mutation.mutate({ remove_proxy_index: i })} className="text-slate-600 hover:text-red-400" aria-label="Proxy sil" title="Sil">
                        <Trash2 className="w-3 h-3" />
                      </button>
                    </div>
                    {tr && (
                      tr.alive
                        ? <span className="text-emerald-400 pl-1">✓ canlı · {tr.latency_ms}ms · çıkış {tr.exit_ip}</span>
                        : <span className="text-red-400 pl-1 truncate" title={tr.error}>✗ {tr.error}</span>
                    )}
                  </div>
                )
              })}
            </div>
          )}

          <div>
            <label className="text-[10px] text-slate-500 uppercase tracking-wider">Proxy ekle</label>
            <div className="flex gap-2 mt-1">
              <input value={singleProxy} onChange={e => setSingleProxy(e.target.value)} placeholder="[2001:db8::1]:8080:kullanıcı:şifre" autoComplete="off"
                onKeyDown={e => e.key === 'Enter' && addProxy()}
                className="flex-1 bg-iuNavy/50 border border-iuBorder rounded-lg px-3 py-2 text-xs text-slate-300 placeholder-slate-600 focus:border-iuGold focus:outline-none font-mono" />
              <button onClick={addProxy} disabled={!singleProxy.trim() || mutation.isPending} aria-label="Proxy ekle"
                className="px-3 py-2 rounded-lg bg-iuGold/10 text-iuGold border border-iuGold/20 hover:bg-iuGold/20 disabled:opacity-40 transition-colors"><Plus className="w-4 h-4" /></button>
            </div>
            <div className="flex items-center gap-3 mt-1">
              <button onClick={() => setShowBulkProxy(v => !v)} className="text-[10px] text-slate-500 hover:text-iuGold">
                {showBulkProxy ? '− toplu yapıştır kapat' : '+ toplu yapıştır (her satır bir proxy)'}
              </button>
              <label className="text-[10px] text-slate-500 hover:text-iuGold cursor-pointer inline-flex items-center gap-1" title=".txt dosyası (her satır bir proxy)">
                <Upload className="w-3 h-3" /> TXT dosyası yükle
                <input type="file" accept=".txt,text/plain" className="hidden"
                  onChange={e => { uploadProxyTxt(e.target.files?.[0]); e.currentTarget.value = '' }} />
              </label>
            </div>
            {showBulkProxy && (
              <div className="mt-1 space-y-1">
                <textarea value={bulkProxies} onChange={e => setBulkProxies(e.target.value)} rows={3}
                  placeholder={"[2001:db8::1]:8080:user:pass\n1.2.3.4:8080:user:pass\n1.2.3.4:3128"}
                  className="w-full bg-iuNavy/50 border border-iuBorder rounded-lg px-3 py-2 text-xs text-slate-300 placeholder-slate-600 focus:border-iuGold focus:outline-none font-mono" />
                <button onClick={addBulkProxies} disabled={!bulkProxies.trim() || mutation.isPending}
                  className="w-full py-1.5 rounded-lg bg-iuGold/10 text-iuGold border border-iuGold/20 hover:bg-iuGold/20 disabled:opacity-40 text-[11px]">Toplu ekle</button>
              </div>
            )}
            <p className="text-[10px] text-slate-600 mt-1 leading-relaxed">
              Format: <code className="text-iuGold/80">host:port</code> · <code className="text-iuGold/80">host:port:user:pass</code> · IPv6: <code className="text-iuGold/80">[adres]:port:user:pass</code>
            </p>
          </div>
        </>
      )}

      {isSB && (
        <>
          {/* Anahtar havuzu durumu */}
          <div className={`flex items-center gap-2 rounded-lg p-2 text-[11px] ${keyCount > 0 ? 'bg-emerald-500/5 text-emerald-400' : 'bg-amber-500/10 text-amber-400'}`}>
            {keyCount > 0 ? <CheckCircle2 className="w-3.5 h-3.5" /> : <AlertTriangle className="w-3.5 h-3.5" />}
            {keyCount > 0 ? `${keyCount} API anahtarı havuzda (aktif: #${activeIdx + 1})` : 'Anahtar yok — aşağıdan ekleyin (yoksa CSV proxy)'}
          </div>

          {/* Anahtar listesi */}
          {previews.length > 0 && (
            <div className="space-y-1 max-h-28 overflow-y-auto">
              {previews.map((p, i) => {
                const tr = testResults[i]
                return (
                <div key={i} className={`flex flex-col gap-0.5 px-2.5 py-1.5 rounded-lg text-[11px] border ${i === activeIdx ? 'border-iuGold/40 bg-iuGold/5' : 'border-iuBorder bg-iuNavy/30'}`}>
                  <div className="flex items-center gap-2">
                    <KeyRound className="w-3 h-3 text-slate-500 flex-shrink-0" />
                    <span className="font-mono text-slate-400 flex-1">#{i + 1} · {p}</span>
                    {i === activeIdx ? (
                      <span className="text-iuGold flex items-center gap-0.5"><Star className="w-3 h-3" /> aktif</span>
                    ) : (
                      <button onClick={() => mutation.mutate({ active_index: i })} className="text-slate-500 hover:text-iuGold" title="Aktif yap">yap</button>
                    )}
                    <button onClick={() => runTest(i)} disabled={testMut.isPending} className="text-slate-600 hover:text-iuGold disabled:opacity-40" aria-label="Anahtarı test et" title="Test et (1 kredi harcar)">
                      <Zap className={`w-3 h-3 ${testingIdx === i && testMut.isPending ? 'animate-pulse text-iuGold' : ''}`} />
                    </button>
                    <button onClick={() => mutation.mutate({ remove_api_key_index: i })} className="text-slate-600 hover:text-red-400" aria-label="Anahtarı sil" title="Sil">
                      <Trash2 className="w-3 h-3" />
                    </button>
                  </div>
                  {tr && (
                    tr.alive
                      ? <span className="text-emerald-400 pl-1 text-[10px]">✓ canlı · {tr.latency_ms}ms · çıkış {tr.exit_ip}</span>
                      : <span className="text-red-400 pl-1 text-[10px] truncate" title={tr.error}>✗ {tr.error}</span>
                  )}
                </div>
                )
              })}
              {keyCount > 1 && (
                <button onClick={() => rotate.mutate()} disabled={rotate.isPending}
                  className="w-full mt-1 py-1.5 rounded-lg bg-iuNavy/50 text-slate-400 border border-iuBorder hover:text-iuGold hover:border-iuGold/30 text-[11px] flex items-center justify-center gap-1.5 transition-colors">
                  <RotateCw className="w-3 h-3" /> Sonraki anahtara geç (biri tükendiyse)
                </button>
              )}
            </div>
          )}

          {/* Anahtar ekle (tek) */}
          <div>
            <label className="text-[10px] text-slate-500 uppercase tracking-wider">API anahtarı ekle</label>
            <div className="flex gap-2 mt-1">
              <input type="password" value={singleKey} onChange={e => setSingleKey(e.target.value)} placeholder="Anahtarı yapıştır" autoComplete="off"
                className="flex-1 bg-iuNavy/50 border border-iuBorder rounded-lg px-3 py-2 text-xs text-slate-300 placeholder-slate-600 focus:border-iuGold focus:outline-none" />
              <button onClick={addSingle} disabled={!singleKey.trim() || mutation.isPending} aria-label="Anahtar ekle"
                className="px-3 py-2 rounded-lg bg-iuGold/10 text-iuGold border border-iuGold/20 hover:bg-iuGold/20 disabled:opacity-40 transition-colors"><Plus className="w-4 h-4" /></button>
            </div>
            <button onClick={() => setShowBulk(v => !v)} className="text-[10px] text-slate-500 hover:text-iuGold mt-1">
              {showBulk ? '− toplu ekleme (txt) kapat' : '+ toplu ekle (her satır bir anahtar)'}
            </button>
            {showBulk && (
              <div className="mt-1 space-y-1">
                <textarea value={bulkKeys} onChange={e => setBulkKeys(e.target.value)} rows={3} placeholder={"anahtar1\nanahtar2\nanahtar3"}
                  className="w-full bg-iuNavy/50 border border-iuBorder rounded-lg px-3 py-2 text-xs text-slate-300 placeholder-slate-600 focus:border-iuGold focus:outline-none font-mono" />
                <button onClick={addBulk} disabled={!bulkKeys.trim() || mutation.isPending}
                  className="w-full py-1.5 rounded-lg bg-iuGold/10 text-iuGold border border-iuGold/20 hover:bg-iuGold/20 disabled:opacity-40 text-[11px]">Toplu ekle</button>
              </div>
            )}
          </div>

          {/* Kalite (kredi maliyeti) */}
          <div>
            <label className="text-[10px] text-slate-500 uppercase tracking-wider">Proxy kalitesi (kredi)</label>
            <div className="grid grid-cols-3 gap-2 mt-1">
              {QUALITIES.map(q => (
                <button key={q.id} onClick={() => mutation.mutate({ quality: q.id })} aria-pressed={quality === q.id} disabled={mutation.isPending}
                  className={`p-2 rounded-lg border text-left transition-all ${quality === q.id ? 'border-iuGold bg-iuGold/10 text-iuGold' : 'border-iuBorder text-slate-400 hover:border-iuBorder/80'}`}>
                  <p className="text-xs font-medium">{q.label}</p>
                  <p className="text-[9px] text-slate-500 leading-tight">{q.hint}</p>
                </button>
              ))}
            </div>
          </div>

          {/* Ülke */}
          <label className="block">
            <span className="text-[10px] text-slate-500 uppercase tracking-wider">Ülke (çıkış IP)</span>
            <select value={country} onChange={e => mutation.mutate({ country: e.target.value })} disabled={mutation.isPending}
              className="mt-1 w-full bg-iuNavy/50 border border-iuBorder rounded-lg px-3 py-2 text-sm text-slate-300 focus:border-iuGold focus:outline-none">
              {COUNTRIES.map(c => <option key={c.code} value={c.code}>{c.label} ({c.code.toUpperCase()})</option>)}
            </select>
          </label>

          {/* JS Render */}
          <div className="flex items-center justify-between">
            <div>
              <p className="text-xs text-slate-400">JS Render</p>
              <p className="text-[10px] text-slate-600">Cookie üretimi için genelde kapalı (kredi artırır)</p>
            </div>
            <button onClick={() => mutation.mutate({ render_js: !renderJs })} disabled={mutation.isPending} aria-pressed={renderJs}
              className={`transition-colors ${renderJs ? 'text-emerald-400' : 'text-slate-600'} disabled:opacity-50`}>
              {renderJs ? <ToggleRight className="w-7 h-7" /> : <ToggleLeft className="w-7 h-7" />}
            </button>
          </div>
        </>
      )}
    </GlassCard>
  )
}
