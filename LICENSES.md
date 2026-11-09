# MORVIX License Inventory

This inventory is an implementation record, not a grant of rights. Verify each model card, dataset, and dependency license when producing the final academic submission.

| Asset | License | Use / limit |
| --- | --- | --- |
| MORVIX source in this workspace | Not assigned | The project team should select and add a repository license before external distribution. |
| `unitary/toxic-bert` | Apache-2.0, as stated by the model card | Local text classification for the model's documented toxic-comment labels. Only its `threat` output is mapped; it is not a self-harm classifier. |
| `jaranohaal/vit-base-violence-detection` | Apache-2.0, as stated by the model card | Candidate weights were downloaded for inspection, but are not used: the published config has no explicit label map and the safetensors keys do not match the documented Transformers architecture. The adapter fails closed. |
| `HappyGook/videomae-violence-detector` | MIT, as stated by the model card | Candidate local temporal video classifier; output map is documented as index 0 non-violent, index 1 violent. It does not provide an image classifier. |
| UCF Crime / Real Life Violence Situations / Jigsaw datasets | Separate dataset terms | No dataset is bundled. Any evaluation or training use must follow the dataset owner's access and redistribution rules. |
| FastAPI, Uvicorn, Pydantic, SQLite, Pillow, Transformers, PyTorch, OpenCV, Hugging Face Hub | Each dependency's own license | Installed from package registries during setup; see the package metadata and notices for the pinned environment. |

Download-time model manifests record exact model revisions under each local model directory. Model weights, user-supplied evaluation data, and databases are excluded from version control.
