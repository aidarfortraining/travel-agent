import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { pdfUrl } from "@/api/client";

export function PlanView({
  markdown,
  sessionId,
  finalized,
  onAccept,
}: {
  markdown: string;
  sessionId: string;
  finalized: boolean;
  onAccept: () => void;
}) {
  return (
    <div className="bg-white rounded-lg shadow p-6 border border-slate-200">
      <div className="markdown-plan">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{markdown}</ReactMarkdown>
      </div>
      <div className="mt-4 flex flex-wrap gap-2">
        {!finalized && (
          <button
            type="button"
            onClick={onAccept}
            className="bg-emerald-600 hover:bg-emerald-700 text-white font-medium px-4 py-2 rounded"
          >
            Принять план
          </button>
        )}
        {finalized && (
          <a
            href={pdfUrl(sessionId)}
            target="_blank"
            rel="noopener noreferrer"
            className="bg-ink hover:bg-slate-700 text-white font-medium px-4 py-2 rounded"
          >
            Скачать PDF
          </a>
        )}
      </div>
    </div>
  );
}
