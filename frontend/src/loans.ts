import { api } from './api.ts'

export function getLoanDetail(id: string) {
  return api<Record<string, unknown>>(`/api/prestamos/${encodeURIComponent(id)}`)
}

const terminalLoanStatuses = new Set(['APROBADA', 'RECHAZADA', 'CANCELADA_SIN_STOCK', 'CANCELADA', 'COMPLETADA'])

export function loansToPoll<T extends { id: string; status: string }>(loans: T[]) {
  return loans.filter((loan) => !terminalLoanStatuses.has(loan.status))
}
