import { useForm, Controller } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import type { TripInput } from "@/api/client";

const INTERESTS = ["history", "food", "art", "architecture", "nature", "nightlife", "shopping", "family"];
const DIETARY = ["halal", "vegan", "vegetarian", "gluten-free", "kosher"] as const;

const schema = z.object({
  city: z.string().min(2, "Минимум 2 символа"),
  days: z.coerce.number().int().min(1).max(14),
  budget_usd: z.coerce.number().min(0),
  interests: z.array(z.string()).min(1, "Выберите хотя бы один интерес"),
  dietary: z.array(z.enum(DIETARY)),
});

type FormShape = z.infer<typeof schema>;

export function TripForm({
  onSubmit,
  disabled,
  initialValues,
}: {
  onSubmit: (payload: TripInput) => void;
  disabled?: boolean;
  initialValues?: Partial<TripInput>;
}) {
  const {
    register,
    handleSubmit,
    control,
    formState: { errors },
  } = useForm<FormShape>({
    resolver: zodResolver(schema),
    defaultValues: {
      city: "Istanbul",
      days: 3,
      budget_usd: 300,
      interests: ["history", "food"],
      dietary: [],
      // dietary values originate from the DIETARY enum buttons, so the loose
      // string[] from TripInput is safe to narrow here.
      ...(initialValues as Partial<FormShape>),
    },
  });

  return (
    <form
      onSubmit={handleSubmit((d) => onSubmit(d as TripInput))}
      className="space-y-4 bg-white rounded-lg shadow p-6 border border-slate-200"
    >
      <h2 className="text-lg font-semibold text-ink">Параметры поездки</h2>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <label className="block">
          <span className="block text-sm font-medium mb-1">Город</span>
          <input
            className="w-full border border-slate-300 rounded px-3 py-2"
            placeholder="Istanbul"
            {...register("city")}
            disabled={disabled}
          />
          {errors.city && <p className="text-red-600 text-xs mt-1">{errors.city.message}</p>}
        </label>

        <label className="block">
          <span className="block text-sm font-medium mb-1">Дней</span>
          <input
            type="number"
            min={1}
            max={14}
            className="w-full border border-slate-300 rounded px-3 py-2"
            {...register("days")}
            disabled={disabled}
          />
        </label>

        <label className="block">
          <span className="block text-sm font-medium mb-1">Бюджет, USD</span>
          <input
            type="number"
            min={0}
            step="10"
            className="w-full border border-slate-300 rounded px-3 py-2"
            {...register("budget_usd")}
            disabled={disabled}
          />
        </label>
      </div>

      <div>
        <span className="block text-sm font-medium mb-1">Интересы</span>
        <Controller
          control={control}
          name="interests"
          render={({ field }) => (
            <div className="flex flex-wrap gap-2">
              {INTERESTS.map((i) => {
                const checked = field.value.includes(i);
                return (
                  <button
                    type="button"
                    key={i}
                    disabled={disabled}
                    aria-pressed={checked}
                    onClick={() =>
                      field.onChange(checked ? field.value.filter((x) => x !== i) : [...field.value, i])
                    }
                    className={
                      "px-3 py-1 rounded-full text-sm border transition " +
                      (checked
                        ? "bg-ink text-white border-ink"
                        : "bg-white text-ink border-slate-300 hover:bg-slate-50")
                    }
                  >
                    {i}
                  </button>
                );
              })}
            </div>
          )}
        />
        {errors.interests && <p className="text-red-600 text-xs mt-1">{errors.interests.message as string}</p>}
      </div>

      <div>
        <span className="block text-sm font-medium mb-1">Пищевые ограничения</span>
        <Controller
          control={control}
          name="dietary"
          render={({ field }) => (
            <div className="flex flex-wrap gap-2">
              {DIETARY.map((d) => {
                const checked = field.value.includes(d);
                return (
                  <button
                    type="button"
                    key={d}
                    disabled={disabled}
                    aria-pressed={checked}
                    onClick={() =>
                      field.onChange(checked ? field.value.filter((x) => x !== d) : [...field.value, d])
                    }
                    className={
                      "px-3 py-1 rounded-full text-sm border transition " +
                      (checked
                        ? "bg-accent text-white border-accent"
                        : "bg-white text-ink border-slate-300 hover:bg-slate-50")
                    }
                  >
                    {d}
                  </button>
                );
              })}
            </div>
          )}
        />
      </div>

      <button
        type="submit"
        disabled={disabled}
        className="bg-ink hover:bg-slate-700 text-white font-medium px-5 py-2 rounded disabled:opacity-50 disabled:cursor-not-allowed"
      >
        {disabled ? "Генерирую план..." : "Построить план"}
      </button>
    </form>
  );
}
