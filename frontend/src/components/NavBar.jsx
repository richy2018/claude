import React, { useState } from 'react';
import { COLORS, FONT } from '../utils/theme.js';

const TABS = [
  { name: 'DASHBOARD',  placeholder: false },
  { name: 'REGIME MAP', placeholder: true  },
  { name: 'CROSS-ASSET', placeholder: false },
  { name: 'EQUITIES',  placeholder: false },
  { name: 'NEWS',      placeholder: true  },
  { name: 'BRIEFING',  placeholder: true  },
];

const styles = {
  nav: {
    display: 'flex',
    alignItems: 'center',
    height: '36px',
    backgroundColor: COLORS.bg,
    borderBottom: `1px solid ${COLORS.cardBorder}`,
    padding: '0 8px',
    boxSizing: 'border-box',
    userSelect: 'none',
  },
  tab: (isActive, isPlaceholder, isHovered) => ({
    display: 'inline-flex',
    alignItems: 'center',
    height: '100%',
    padding: '0 16px',
    cursor: isPlaceholder ? 'default' : 'pointer',
    fontFamily: FONT,
    fontSize: '13px',
    letterSpacing: '1px',
    textTransform: 'uppercase',
    whiteSpace: 'nowrap',
    boxSizing: 'border-box',
    borderBottom: isActive
      ? `2px solid ${COLORS.amber}`
      : '2px solid transparent',
    color: isActive
      ? COLORS.amber
      : isPlaceholder
        ? '#333333'
        : isHovered
          ? '#888888'
          : COLORS.textMuted,
    transition: 'color 0.15s ease',
    marginBottom: '-1px', // sit flush on the border-bottom of the nav
  }),
};

function Tab({ name, isActive, isPlaceholder, onTabChange }) {
  const [hovered, setHovered] = useState(false);

  const handleClick = () => {
    if (!isPlaceholder && onTabChange) {
      onTabChange(name);
    }
  };

  return (
    <div
      style={styles.tab(isActive, isPlaceholder, hovered)}
      onClick={handleClick}
      onMouseEnter={() => !isPlaceholder && setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      title={isPlaceholder ? 'Coming soon' : name}
    >
      {name}
    </div>
  );
}

export default function NavBar({ activeTab, onTabChange }) {
  return (
    <nav style={styles.nav}>
      {TABS.map(({ name, placeholder }) => (
        <Tab
          key={name}
          name={name}
          isActive={activeTab === name}
          isPlaceholder={placeholder}
          onTabChange={onTabChange}
        />
      ))}
    </nav>
  );
}
