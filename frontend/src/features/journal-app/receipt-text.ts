/** A sentence as the receipt bar shows it: its messages have no closing full stop ("Anteckningen är ändrad"). */
export function receiptText(sentence: string): string {
  return sentence.replace(/\.$/, "");
}
