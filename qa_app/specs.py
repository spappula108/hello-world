"""Specification repository for materials and stages.

Loads a JSON file with specification parameters and provides helpers for lookup.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional, Tuple


class SpecsRepository:
    def __init__(self, data_dir: str) -> None:
        self.data_dir = data_dir
        self.specs_path = os.path.join(data_dir, "specs.json")
        self._specs: Dict[str, Any] = {}

    def load(self) -> None:
        if not os.path.exists(self.specs_path):
            os.makedirs(self.data_dir, exist_ok=True)
            # Create minimal demo specs
            demo = {
                "Paracetamol": {
                    "Raw Material": {
                        "tests": {
                            "Assay (HPLC %)": {"min": 98.0, "max": 102.0},
                            "Moisture (%)": {"max": 0.5},
                            "Related Substances (max %)": {"max": 0.2},
                        },
                        "sop": "SOP-001-RAW",
                    },
                    "Finished Product": {
                        "tests": {
                            "Assay (HPLC %)": {"min": 95.0, "max": 105.0},
                            "Dissolution (Q %)": {"min": 80.0},
                            "Uniformity of Dosage Units (AV)": {"max": 15.0},
                        },
                        "sop": "SOP-002-FP",
                    },
                },
                "Ibuprofen": {
                    "Raw Material": {
                        "tests": {
                            "Assay (HPLC %)": {"min": 97.0, "max": 103.0},
                            "Moisture (%)": {"max": 0.3},
                        },
                        "sop": "SOP-003-RAW",
                    }
                },
            }
            with open(self.specs_path, "w", encoding="utf-8") as f:
                json.dump(demo, f, indent=2)

        with open(self.specs_path, "r", encoding="utf-8") as f:
            self._specs = json.load(f)

    # --- helpers ---
    def materials(self) -> List[str]:
        return sorted(list(self._specs.keys()))

    def stages_for_material(self, material: str) -> List[str]:
        return sorted(list(self._specs.get(material, {}).keys()))

    def get_spec(self, material: str, stage: str) -> Optional[Dict[str, Any]]:
        return self._specs.get(material, {}).get(stage)

    def test_fields(self, material: str, stage: str) -> List[Tuple[str, Dict[str, Any]]]:
        spec = self.get_spec(material, stage)
        if not spec:
            return []
        tests = spec.get("tests", {})
        return list(tests.items())

    def sop_code(self, material: str, stage: str) -> Optional[str]:
        spec = self.get_spec(material, stage)
        if not spec:
            return None
        return spec.get("sop")

