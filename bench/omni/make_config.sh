#!/usr/bin/env bash
# usage: bench/omni/make_config.sh <gt.json> <pred_dir> > config.yaml   (CDM omitted: needs TeX Live/ImageMagick)
cat <<YAML
end2end_eval:
  metrics:
    text_block:
      metric: [Edit_dist]
    display_formula:
      metric: [Edit_dist]
    table:
      metric: [TEDS, Edit_dist]
      teds_workers: ${OMNI_WORKERS:-6}
    reading_order:
      metric: [Edit_dist]
  dataset:
    dataset_name: end2end_dataset
    ground_truth:
      data_path: $1
    prediction:
      data_path: $2
    match_method: quick_match
    match_workers: ${OMNI_WORKERS:-6}
    quick_match_truncated_timeout_sec: 300
    match_timeout_sec: 420
    timeout_fallback_max_chunk_span: 10
    timeout_fallback_order_penalty: 0.10
YAML
