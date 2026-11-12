// The only icons on the site: inline SVG paths (24 x 24 viewBox), no external icon library.
// Each entry: [attributes for the <svg>, inner markup].
type Icon = { fill?: string; stroke?: boolean; inner: string };

export const icons: Record<string, Icon> = {
  search: { stroke: true, inner: '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>' },
  menu: { stroke: true, inner: '<path d="M4 7h16M4 12h16M4 17h16"/>' },
  check: { stroke: true, inner: '<path d="m5 12.5 4.5 4.5L19 7.5"/>' },
  circle: { stroke: true, inner: '<circle cx="12" cy="12" r="7.5"/>' },
  info: { stroke: true, inner: '<circle cx="12" cy="12" r="9"/><path d="M12 11v5.5M12 7.8v.2"/>' },
  warning: { stroke: true, inner: '<path d="M12 3.5 2.8 19.5h18.4L12 3.5Z"/><path d="M12 10v4.5M12 17v.3"/>' },
  edit: { stroke: true, inner: '<path d="M4 20h4L19 9l-4-4L4 16v4Z"/><path d="m13.5 6.5 4 4"/>' },
  external: { stroke: true, inner: '<path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/>' },
};
