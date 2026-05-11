import type { ReactNode } from "react";

interface Props {
  title: string;
  description?: ReactNode;
  icon?: ReactNode;
}

export function Empty({ title, description, icon }: Props) {
  return (
    <div className="card flex items-center gap-4">
      {icon && <div className="text-slate-600">{icon}</div>}
      <div>
        <div className="text-sm font-medium text-slate-200">{title}</div>
        {description && (
          <div className="mt-1 text-xs text-slate-500">{description}</div>
        )}
      </div>
    </div>
  );
}
