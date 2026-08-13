import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import type { HealthResponse, DetailedHealthResponse } from '../types'

export function useSystemHealth() {
  return useQuery<HealthResponse>({
    queryKey: ['system-health'],
    queryFn: () => api.getHealth(),
    refetchInterval: 4_000,   // canlı RAM/CPU göstergesi için sık
  })
}

export function useSystemHealthDetailed() {
  return useQuery<DetailedHealthResponse>({
    queryKey: ['system-health-detailed'],
    queryFn: () => api.getHealthDetailed(),
    refetchInterval: 60_000,
  })
}
