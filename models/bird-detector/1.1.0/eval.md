# bird-detector v1.1.0 — Evaluation

## Source
Fine-tuned from `models/bird-detector/1.0.0/model.pt` on `datasets/bird-detector.yaml`.

## Run
- Run dir: `runs/detect/runs/train/bird-detector-20260527-022229`
- Epochs: 80 (early-stop patience 20)
- imgsz: 640, batch: 8, seed: 0

## Validation metrics (best.pt)
| Metric    | Value |
|-----------|-------|
| mAP@50    | 0.8089 |
| mAP@50:95 | 0.4421 |
| Precision | 0.8312 |
| Recall    | 0.7467 |

## Reproducing
```bash
python scripts/train_bird_detector.py \
    --data datasets/bird-detector.yaml \
    --weights models/bird-detector/1.0.0/model.pt \
    --epochs 80 --imgsz 640 \
    --version 1.1.0
```

## Next steps
- Spot-check predictions on held-out shed footage.
- If recall on dark / heavily-occluded frames is weak, augment dataset
  and re-train into v1.1.0+1.
- After acceptance: `cd models/bird-detector && ln -snf 1.1.0 latest`,
  then bump `EdgeConfig.ai.models[*].version` on the device.
