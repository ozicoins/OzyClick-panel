import { useCallback } from 'react'
import { useDropzone } from 'react-dropzone'
import { Upload, FileText } from 'lucide-react'
import { useMutation } from '@tanstack/react-query'
import { api } from '../api/client'
import toast from 'react-hot-toast'
import type { GmailAccount } from '../types'
import GlassCard from './ui/GlassCard'
import PanelHeader from './ui/PanelHeader'
import EmptyState from './ui/EmptyState'

interface Props {
  accounts: GmailAccount[]
  onAccountsLoaded: (accounts: GmailAccount[]) => void
  onFarmSingle: (email: string) => void
}

export default function CsvUploader({ accounts, onAccountsLoaded, onFarmSingle }: Props) {
  const upload = useMutation({
    mutationFn: (file: File) => api.uploadCsv(file),
    onSuccess: (data) => {
      onAccountsLoaded(data.accounts)
      toast.success(data.message)
    },
    onError: (e: Error) => toast.error(e.message),
  })

  const onDrop = useCallback((files: File[]) => {
    if (files[0]) upload.mutate(files[0])
  }, [upload])

  const onDropRejected = useCallback(() => {
    toast.error('Dosya reddedildi: yalnızca .txt / .csv, maksimum 10 MB')
  }, [])

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    onDropRejected,
    accept: { 'text/plain': ['.txt'], 'text/csv': ['.csv'] },
    maxFiles: 1,
    maxSize: 10 * 1024 * 1024,  // backend max_upload_bytes ile hizalı
  })

  return (
    <GlassCard className="space-y-4">
      <PanelHeader icon={FileText} title="Hesap Yönetimi (TXT / CSV)" />

      <div
        {...getRootProps()}
        role="button"
        tabIndex={0}
        aria-label="TXT veya CSV dosyası yükle"
        className={`border-2 border-dashed rounded-xl p-4 sm:p-6 text-center cursor-pointer transition-all
          ${isDragActive ? 'border-iuGold bg-iuGold/5' : 'border-iuBorder hover:border-iuGold/40'}`}
      >
        <input {...getInputProps()} />
        <Upload className="w-6 h-6 sm:w-8 sm:h-8 mx-auto text-slate-500 mb-2" aria-hidden="true" />
        <p className="text-xs sm:text-sm text-slate-400">
          {upload.isPending
            ? 'Yükleniyor...'
            : isDragActive
              ? 'Bırakın...'
              : '.txt / .csv dosyasını sürükleyin veya tıklayın'}
        </p>
      </div>

      <div className="text-[10px] text-slate-600 bg-iuNavy/30 rounded-lg p-2.5 leading-relaxed">
        <p className="text-slate-400 mb-0.5">TXT formatı (her satır bir hesap):</p>
        <code className="text-iuGold/80 break-all">mail:şifre:2fa:proxy:port:kullanıcı:şifre</code>
        <p className="mt-0.5">2fa ve sonrası isteğe bağlı — otomatik algılanır.</p>
      </div>

      {accounts.length > 0 && (
        <div className="overflow-x-auto -mx-5 px-5">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-left text-slate-500 border-b border-iuBorder">
                <th className="pb-2 pr-3">Email</th>
                <th className="pb-2 pr-3 hidden sm:table-cell">Proxy</th>
                <th className="pb-2 pr-3">Mod</th>
                <th className="pb-2">İşlem</th>
              </tr>
            </thead>
            <tbody>
              {accounts.map((acc, i) => (
                <tr key={acc.email || i} className="border-b border-iuBorder/30 hover:bg-white/[0.02]">
                  <td className="py-2 pr-3 text-slate-300 max-w-[140px] truncate">{acc.email}</td>
                  <td className="py-2 pr-3 text-slate-500 max-w-[120px] truncate hidden sm:table-cell">
                    {acc.proxy_ip || '-'}
                  </td>
                  <td className="py-2 pr-3">
                    <span className="px-2 py-0.5 rounded-full text-[10px] bg-iuGold/10 text-iuGold border border-iuGold/20">
                      {acc.farming_mode || 'SAFE'}
                    </span>
                  </td>
                  <td className="py-2">
                    <button
                      onClick={() => onFarmSingle(acc.email)}
                      className="px-2 py-1 text-[10px] rounded bg-iuGold/10 text-iuGold hover:bg-iuGold/20 transition-colors"
                    >
                      Seç
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </GlassCard>
  )
}
