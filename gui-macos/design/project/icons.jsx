// icons.jsx — minimal stroke icons. Mirrors SF Symbols where possible.
// 14×14 default; pass size via props.

const Icon = ({ name, size = 14, className = '', style = {} }) => {
  const props = {
    width: size, height: size,
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.6,
    strokeLinecap: "round",
    strokeLinejoin: "round",
    className: className,
    style: style,
  };
  switch (name) {
    case 'tray':       return <svg {...props}><path d="M3 13l2.5-7a2 2 0 0 1 1.9-1.4h9.2a2 2 0 0 1 1.9 1.4L21 13"/><path d="M3 13h6l1 2h4l1-2h6v5a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-5z"/></svg>;
    case 'folder':     return <svg {...props}><path d="M3 7a2 2 0 0 1 2-2h3.5l2 2H19a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7z"/></svg>;
    case 'folder-fill':return <svg {...props} fill="currentColor" stroke="none"><path d="M3 7a2 2 0 0 1 2-2h3.5l2 2H19a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7z"/></svg>;
    case 'plus':       return <svg {...props}><path d="M12 5v14M5 12h14"/></svg>;
    case 'minus':      return <svg {...props}><path d="M5 12h14"/></svg>;
    case 'x':          return <svg {...props}><path d="M6 6l12 12M18 6L6 18"/></svg>;
    case 'check':      return <svg {...props}><path d="M5 12.5L10 17.5L19 7.5"/></svg>;
    case 'search':     return <svg {...props}><circle cx="11" cy="11" r="6.5"/><path d="m20 20-3.5-3.5"/></svg>;
    case 'sort':       return <svg {...props}><path d="M7 4v16M3 8l4-4 4 4M17 20V4M21 16l-4 4-4-4"/></svg>;
    case 'tag':        return <svg {...props}><path d="M3 12V4h8l10 10-8 8L3 12z"/><circle cx="8" cy="9" r="1.4" fill="currentColor"/></svg>;
    case 'note':       return <svg {...props}><path d="M5 4h10l4 4v12a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1z"/><path d="M15 4v4h4"/></svg>;
    case 'quote':      return <svg {...props}><path d="M6 7h4v4H7c0 2 1 3 3 3v2c-3 0-5-2-5-5V7zM14 7h4v4h-3c0 2 1 3 3 3v2c-3 0-5-2-5-5V7z"/></svg>;
    case 'arrow-up':   return <svg {...props}><path d="M12 19V5M5 12l7-7 7 7"/></svg>;
    case 'arrow-right':return <svg {...props}><path d="M5 12h14M13 5l7 7-7 7"/></svg>;
    case 'chevron-r':  return <svg {...props}><path d="M9 6l6 6-6 6"/></svg>;
    case 'chevron-d':  return <svg {...props}><path d="M6 9l6 6 6-6"/></svg>;
    case 'pen':        return <svg {...props}><path d="M16 4l4 4-11 11H5v-4L16 4z"/></svg>;
    case 'trash':      return <svg {...props}><path d="M4 7h16M9 7V4h6v3M6 7l1 13a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1l1-13"/></svg>;
    case 'merge':      return <svg {...props}><path d="M6 4v6c0 4 6 4 6 8v2M18 4v6c0 4-6 4-6 8"/></svg>;
    case 'bolt-slash': return <svg {...props}><path d="M13 3 6 13h5l-2 8 9-12h-5l2-6z"/><path d="M3 3l18 18"/></svg>;
    case 'sparkle':    return <svg {...props}><path d="M12 4v6M12 14v6M4 12h6M14 12h6M7 7l3 3M14 14l3 3M17 7l-3 3M10 14l-3 3"/></svg>;
    case 'circle-half': return <svg {...props}><circle cx="12" cy="12" r="8"/><path d="M12 4v16" /><path d="M12 4a8 8 0 0 1 0 16" fill="currentColor" stroke="none"/></svg>;
    case 'list':       return <svg {...props}><path d="M8 6h13M8 12h13M8 18h13"/><circle cx="4" cy="6" r="1" fill="currentColor"/><circle cx="4" cy="12" r="1" fill="currentColor"/><circle cx="4" cy="18" r="1" fill="currentColor"/></svg>;
    case 'rows':       return <svg {...props}><rect x="3" y="4" width="18" height="6" rx="1.5"/><rect x="3" y="14" width="18" height="6" rx="1.5"/></svg>;
    case 'rows-dense': return <svg {...props}><path d="M3 6h18M3 10h18M3 14h18M3 18h18"/></svg>;
    case 'gear':       return <svg {...props}><circle cx="12" cy="12" r="3"/><path d="M12 3v2M12 19v2M3 12h2M19 12h2M5.6 5.6l1.4 1.4M17 17l1.4 1.4M5.6 18.4 7 17M17 7l1.4-1.4"/></svg>;
    case 'kbd-cmd':    return <svg {...props}><path d="M9 9V7a2 2 0 1 0-2 2h10a2 2 0 1 0-2-2v2M9 15v2a2 2 0 1 1-2-2h10a2 2 0 1 1-2 2v-2M9 9h6v6H9z"/></svg>;
    case 'eye':        return <svg {...props}><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/></svg>;
    case 'inbox-down': return <svg {...props}><path d="M3 13h6l1 2h4l1-2h6v5a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-5z"/><path d="M12 4v8M9 9l3 3 3-3"/></svg>;
    case 'star':       return <svg {...props}><path d="M12 4l2.5 5.5L20 11l-4 4 1 5.5L12 18l-5 2.5 1-5.5-4-4 5.5-1.5L12 4z"/></svg>;
    case 'archive':    return <svg {...props}><rect x="3" y="4" width="18" height="4" rx="1"/><path d="M5 8v10a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V8M10 12h4"/></svg>;
    case 'link':       return <svg {...props}><path d="M10 13a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1M14 11a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"/></svg>;
    case 'copy':       return <svg {...props}><rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2"/></svg>;
    case 'split':      return <svg {...props}><path d="M3 5h18M3 19h18"/><circle cx="12" cy="12" r="2.5"/></svg>;
    case 'arrows-curve':return <svg {...props}><path d="M5 6c0 6 14 6 14 12M14 18l5-1M19 17l-1 5"/></svg>;
    case 'wrench':     return <svg {...props}><path d="M14 6a4 4 0 1 0 4 4l3 3-3 3-3-3a4 4 0 1 1-4-4l-3-3 3-3 3 3z"/></svg>;
    case 'info':       return <svg {...props}><circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8v.5"/></svg>;
    case 'warn':       return <svg {...props}><path d="M12 4l10 16H2L12 4zM12 10v4M12 17v.5"/></svg>;
    default:           return <svg {...props}><circle cx="12" cy="12" r="9"/></svg>;
  }
};

window.Icon = Icon;
