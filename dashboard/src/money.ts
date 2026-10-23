/** Turn a dollar string from the API, such as "1250.50", into whole cents. */
export function toCents(amount: string): number {
  const [dollars = "0", fraction = ""] = amount.split(".");
  return Number(dollars) * 100 + Number(fraction.padEnd(2, "0").slice(0, 2));
}

/** Show whole cents as US dollars, such as $1,250.00. */
export function formatCents(cents: number): string {
  const dollars = Math.floor(cents / 100).toLocaleString("en-US");
  return `$${dollars}.${String(cents % 100).padStart(2, "0")}`;
}
