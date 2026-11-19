export type LoanRequestBody = {
  customer_id: string
  product_id: number
  quantity: number
  term_months: number
}

export type LoanRequestAttempt = { key: string; body: LoanRequestBody }

export class LoanSubmissionAttempt {
  private attempt: LoanRequestAttempt | null = null

  getOrCreate(body: LoanRequestBody, createKey = () => crypto.randomUUID()): LoanRequestAttempt {
    if (!this.attempt) this.attempt = { key: createKey(), body: { ...body } }
    return this.attempt
  }

  clear() {
    this.attempt = null
  }

  current() {
    return this.attempt
  }
}
