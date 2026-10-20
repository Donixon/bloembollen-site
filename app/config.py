from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    admin_token: str | None
    coord_decimals: int
    max_upload_mb: int

    @classmethod
    def from_env(cls) -> "Settings":
        coord_decimals = int(os.getenv("COORD_DECIMALS", "2"))
        max_upload_mb = int(os.getenv("MAX_UPLOAD_MB", "15"))
        if not 0 <= coord_decimals <= 6:
            raise ValueError("COORD_DECIMALS moet tussen 0 en 6 liggen.")
        if max_upload_mb < 1:
            raise ValueError("MAX_UPLOAD_MB moet minimaal 1 zijn.")
        return cls(
            data_dir=Path(os.getenv("DATA_DIR", "/data")),
            admin_token=os.getenv("ADMIN_TOKEN") or None,
            coord_decimals=coord_decimals,
            max_upload_mb=max_upload_mb,
        )

    @property
    def database_path(self) -> Path:
        return self.data_dir / "app.db"

    @property
    def photos_dir(self) -> Path:
        return self.data_dir / "uploads" / "photos"

    @property
    def thumbs_dir(self) -> Path:
        return self.data_dir / "uploads" / "thumbs"
