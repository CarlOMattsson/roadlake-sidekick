/**
 * The receipt after a message to Claude went into the conversation ("Tell Claude about the day"): the host shows no
 * answer in the room, so the receipt says where it comes. Spread into journalEn and journalSv (label-parts.ts).
 */
export const receiptEn = {
  tellClaudeSent: "Sent to Claude – answer in the chat",
};
export const receiptSv: typeof receiptEn = {
  tellClaudeSent: "Skickat till Claude – svara i chatten",
};
