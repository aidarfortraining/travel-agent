# A/B Experiment: mini-41 vs mini-4o

## Results

| Metric | mini-41 | mini-4o | Δ |
|---|---|---|---|
| constraint_adherence | 0.800 | 0.800 | +0.000 |
| faithfulness | 0.965 | 0.507 | -0.458 |

## Notes

- All runs share the same golden dataset (`trip-planner-golden-v1`).
- LLM-as-judge metrics use the project's primary OpenAI mini model at temperature 0.0.
- Differences below 0.05 are within noise on 10-example datasets.
