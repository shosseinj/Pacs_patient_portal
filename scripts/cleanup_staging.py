"""Remove only old published-job staging. Archive and DB records are retained."""

import argparse
import shutil
import time
from sqlalchemy import select
from sqlalchemy.orm import Session
from portal.auth import audit
from portal.config import Settings
from portal.db import make_engine
from portal.models import UploadJob


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.days < 1:
        parser.error("Keep at least one day")
    settings = Settings.from_env()
    with Session(make_engine(settings.database_url)) as db:
        jobs = db.scalars(
            select(UploadJob).where(
                UploadJob.status == "published", UploadJob.updated_at < time.time() - args.days * 86400
            )
        ).all()
        count = 0
        for job in jobs:
            folder = settings.upload_dir / job.id
            if folder.exists():
                count += 1
                if args.apply:
                    shutil.rmtree(folder)
                    audit(db, None, "staging_removed", job.id)
        if args.apply:
            db.commit()
        print(
            f"{count} old published staging directories "
            + ("removed" if args.apply else "eligible; use --apply to remove")
        )


if __name__ == "__main__":
    main()
