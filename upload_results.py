import os
from pathlib import Path

import boto3


results_dir = Path(r"D:\rustfs\results")

s3 = boto3.client(
    "s3",
    endpoint_url="http://localhost:9000",
    aws_access_key_id=os.environ["RUSTFS_ACCESS_KEY"],
    aws_secret_access_key=os.environ["RUSTFS_SECRET_KEY"],
    region_name="us-east-1",
)

for configuration in ("4-disks", "6-disks", "8-disks"):
    for filename in ("mapreduce_counts.csv", "duckdb_counts.csv"):
        path = results_dir / configuration / filename
        key = f"results/{configuration}/{filename}"

        s3.upload_file(str(path), "hh-lake", key)
        print(f"Загружен: s3://hh-lake/{key}")

profile_path = results_dir / "stage3_profile.csv"
s3.upload_file(
    str(profile_path),
    "hh-lake",
    "results/profiling/stage3_profile.csv",
)
print("Загружен: s3://hh-lake/results/profiling/stage3_profile.csv")