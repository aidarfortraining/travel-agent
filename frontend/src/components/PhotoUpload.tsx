import { useState } from "react";
import { uploadPhoto } from "@/api/client";

export function PhotoUpload({ sessionId, disabled }: { sessionId: string | null; disabled?: boolean }) {
  const [name, setName] = useState<string>("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onChange(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0];
    if (!f || !sessionId) return;
    setError(null);
    setBusy(true);
    try {
      await uploadPhoto(sessionId, f);
      setName(f.name);
    } catch (err: any) {
      setError(err.message || "upload failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="bg-white rounded-lg shadow p-4 border border-slate-200">
      <h3 className="text-sm font-semibold mb-2">Фото места (опционально)</h3>
      <p className="text-xs text-slate-500 mb-2">
        Если вы хотите, чтобы конкретное место было в плане — загрузите фото. Vision определит landmark.
      </p>
      <input type="file" accept="image/*" onChange={onChange} disabled={disabled || busy || !sessionId} />
      {name && <p className="text-xs text-emerald-600 mt-2">Загружено: {name}</p>}
      {error && <p className="text-xs text-red-600 mt-2">{error}</p>}
    </div>
  );
}
