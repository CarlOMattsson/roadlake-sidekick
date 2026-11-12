// Syntax colours for code blocks (Expressive Code needs literal colours; design.md 2.1).
// All pairs are at least 4.5:1 against the code background (#f4f4f5 / #242427).
const make = (type, c) => ({
  name: `sidekick-${type}`,
  type,
  colors: { 'editor.background': c.bg, 'editor.foreground': c.fg },
  tokenColors: [
    { scope: ['comment', 'punctuation.definition.comment'], settings: { foreground: c.comment, fontStyle: 'italic' } },
    { scope: ['keyword', 'storage', 'entity.name.tag', 'support.function', 'entity.name.function'], settings: { foreground: c.key } },
    { scope: ['string', 'string.quoted', 'constant.other.symbol'], settings: { foreground: c.string } },
    { scope: ['variable.other.placeholder', 'constant.numeric', 'constant.language', 'variable.parameter'], settings: { foreground: c.placeholder } },
  ],
});
export const lightTheme = make('light', { bg: '#f4f4f5', fg: '#1f1f1f', comment: '#5f6368', key: '#7c3aed', string: '#0f766e', placeholder: '#b45309' });
export const darkTheme = make('dark', { bg: '#242427', fg: '#ededed', comment: '#a1a1aa', key: '#c4b5fd', string: '#5eead4', placeholder: '#fcd34d' });
