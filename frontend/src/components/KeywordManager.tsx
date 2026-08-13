import { useState, useEffect } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import { Tags, Plus, X } from 'lucide-react'
import toast from 'react-hot-toast'
import GlassCard from './ui/GlassCard'
import PanelHeader from './ui/PanelHeader'

const SECTORS = [
  'Alışveriş (E-Ticaret Harmanı)',
  'Pazaryerleri & Dev Siteler',
  'Teknoloji & Elektronik',
  'Moda & Giyim',
  'Kozmetik & Kişisel Bakım',
  'Ev, Yaşam & Dekorasyon',
  'Süpermarket & Hızlı Teslimat',
  'Eğitim & Kitap',
  'Araç Kiralama & Rent a Car',
]

interface Props {
  selectedSector: string
  onSectorChange: (sector: string) => void
  keywords: string[]
  onKeywordsChange: (keywords: string[]) => void
}

export default function KeywordManager({ selectedSector, onSectorChange, keywords, onKeywordsChange }: Props) {
  const [newKeyword, setNewKeyword] = useState('')
  const queryClient = useQueryClient()

  // Sektör seçilince o sektörün ısıtma kelimelerini backend'den yükle → çipler dolar.
  // (Önceden getKeywords hiç çağrılmıyordu; bu yüzden liste hep boştu.)
  const { data: sectorData } = useQuery({
    queryKey: ['sector-keywords', selectedSector],
    queryFn: () => api.getKeywords(selectedSector),
    enabled: !!selectedSector,
  })

  useEffect(() => {
    if (sectorData?.keywords) onKeywordsChange(sectorData.keywords)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sectorData])

  const updateMutation = useMutation({
    // Sektörü mutation değişkeninden geçir → istek sürerken sektör değişse bile sonuç
    // DOĞRU sektörün cache'ine yazılır (kapanış değil, snapshot).
    mutationFn: ({ sector, kws }: { sector: string; kws: string[] }) => api.setKeywords(sector, kws),
    onSuccess: (res, { sector }) => {
      queryClient.setQueryData(['sector-keywords', sector], res)
      toast.success('Kelimeler güncellendi')
    },
    onError: (e: Error) => toast.error(e.message),
  })

  const addKeyword = () => {
    const trimmed = newKeyword.trim()
    if (!trimmed || keywords.includes(trimmed)) return
    const updated = [...keywords, trimmed]
    onKeywordsChange(updated)
    updateMutation.mutate({ sector: selectedSector, kws: updated })
    setNewKeyword('')
  }

  const removeKeyword = (index: number) => {
    const updated = keywords.filter((_, i) => i !== index)
    onKeywordsChange(updated)
    updateMutation.mutate({ sector: selectedSector, kws: updated })
  }

  return (
    <GlassCard className="space-y-4">
      <PanelHeader icon={Tags} title="Sektörel Isıtma Kelimeleri" />

      <label className="block">
        <span className="sr-only">Sektör seç</span>
        <select
          value={selectedSector}
          onChange={e => onSectorChange(e.target.value)}
          className="w-full bg-iuNavy/50 border border-iuBorder rounded-lg px-3 py-2 text-sm text-slate-300 focus:border-iuGold focus:outline-none focus:ring-1 focus:ring-iuGold/30"
        >
          {SECTORS.map(s => (
            <option key={s} value={s}>{s}</option>
          ))}
        </select>
      </label>

      {keywords.length > 0 && (
        <div className="flex flex-wrap gap-2 max-h-44 overflow-y-auto pr-1" role="list" aria-label="Seçili kelimeler">
          {keywords.map((kw, i) => (
            <span
              key={`${kw}-${i}`}
              role="listitem"
              className="flex items-center gap-1 px-2.5 py-1 rounded-full text-xs bg-iuGold/10 text-iuGold border border-iuGold/20"
            >
              {kw}
              <button
                onClick={() => removeKeyword(i)}
                className="hover:text-red-400 transition-colors"
                aria-label={`${kw} kaldır`}
              >
                <X className="w-3 h-3" />
              </button>
            </span>
          ))}
        </div>
      )}

      <div className="flex gap-2">
        <input
          value={newKeyword}
          onChange={e => setNewKeyword(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && addKeyword()}
          placeholder="Özel kelime ekle..."
          aria-label="Yeni kelime gir"
          className="flex-1 bg-iuNavy/50 border border-iuBorder rounded-lg px-3 py-1.5 text-xs text-slate-300 placeholder-slate-600 focus:border-iuGold focus:outline-none focus:ring-1 focus:ring-iuGold/30"
        />
        <button
          onClick={addKeyword}
          disabled={!newKeyword.trim()}
          aria-label="Kelime ekle"
          className="px-3 py-1.5 rounded-lg bg-iuGold/10 text-iuGold hover:bg-iuGold/20 disabled:opacity-30 transition-colors"
        >
          <Plus className="w-4 h-4" />
        </button>
      </div>

      {keywords.length > 0 && (
        <div className="bg-iuNavy/30 rounded-lg p-3 text-[11px] text-slate-500">
          <p className="text-slate-400 mb-1">Bu oturumda şu aramalar yapılacak:</p>
          {keywords.slice(0, 5).map((kw, i) => (
            <p key={i}>"{kw}"</p>
          ))}
          {keywords.length > 5 && <p>+{keywords.length - 5} daha...</p>}
        </div>
      )}
    </GlassCard>
  )
}
