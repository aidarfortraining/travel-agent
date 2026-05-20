import { useState } from "react";

export function EditBox({ onSubmit, disabled }: { onSubmit: (text: string) => void; disabled?: boolean }) {
  const [text, setText] = useState("");
  return (
    <div className="bg-white rounded-lg shadow p-4 border border-slate-200">
      <h3 className="text-sm font-semibold mb-2">Правка плана</h3>
      <p className="text-xs text-slate-500 mb-2">
        Например: "убери музеи", "добавь халяль", "максимум $40 в день на еду", "вместо музея — парк".
      </p>
      <textarea
        className="w-full border border-slate-300 rounded px-3 py-2 min-h-[80px]"
        value={text}
        onChange={(e) => setText(e.target.value)}
        disabled={disabled}
        placeholder="Опишите изменения..."
      />
      <div className="mt-2 flex justify-end">
        <button
          type="button"
          disabled={disabled || !text.trim()}
          onClick={() => {
            const t = text.trim();
            if (!t) return;
            onSubmit(t);
            setText("");
          }}
          className="bg-accent hover:bg-amber-700 text-white font-medium px-4 py-2 rounded disabled:opacity-50"
        >
          Применить правку
        </button>
      </div>
    </div>
  );
}
