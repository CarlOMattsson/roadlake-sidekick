/** An amount in US dollars with two decimals in the locale's digits: "0,50 USD" / "0.50 USD". */
export function usd(amount: number, dateLocale: string): string {
  return `${amount.toLocaleString(dateLocale, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })} USD`;
}
