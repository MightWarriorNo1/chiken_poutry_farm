interface Props<T extends string> {
  tabs: { id: T; label: string; count?: number }[];
  active: T;
  onChange: (id: T) => void;
}

export function Tabs<T extends string>({ tabs, active, onChange }: Props<T>) {
  return (
    <nav className="border-b border-ink-800 bg-ink-950">
      <div className="mx-auto flex max-w-7xl items-center gap-1 px-6">
        {tabs.map((t) => {
          const isActive = t.id === active;
          return (
            <button
              key={t.id}
              onClick={() => onChange(t.id)}
              className={`relative px-3 py-3 text-sm transition-colors ${
                isActive
                  ? "text-slate-100"
                  : "text-slate-500 hover:text-slate-300"
              }`}
            >
              {t.label}
              {t.count !== undefined && t.count > 0 && (
                <span className="ml-2 rounded-full bg-ink-700 px-1.5 py-0.5 text-xs tabular-nums text-slate-300">
                  {t.count}
                </span>
              )}
              {isActive && (
                <span className="absolute inset-x-0 bottom-0 h-0.5 bg-sky-400" />
              )}
            </button>
          );
        })}
      </div>
    </nav>
  );
}
