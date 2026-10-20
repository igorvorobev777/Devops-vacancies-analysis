import csv
import itertools
import os
from collections import Counter
from pathlib import Path

import boto3
import duckdb


BUCKET = "hh-lake"
OBJECT_KEY = "devops_vacancies.csv"
S3_URI = f"s3://{BUCKET}/{OBJECT_KEY}"

CHUNK_SIZE = 2000

S3_ENDPOINT = "localhost:9000"
S3_REGION = "us-east-1"
ACCESS_KEY = os.environ["RUSTFS_ACCESS_KEY"]
SECRET_KEY = os.environ["RUSTFS_SECRET_KEY"]

RESULTS_DIR = Path(r"D:\rustfs\results")


def parse_skills(value):
    if not value:
        return []

    return sorted({
        skill.strip().lower()
        for skill in value.split(";")
        if skill.strip()
    })


def count_combinations(rows):
    counts = Counter()

    for row in rows:
        skills = parse_skills(row["key_skills"])

        for size in (1, 2, 3):
            for combination in itertools.combinations(skills, size):
                counts[combination] += 1

    return counts


def mapreduce_counts():
    s3 = boto3.client(
        "s3",
        endpoint_url=f"http://{S3_ENDPOINT}",
        aws_access_key_id=ACCESS_KEY,
        aws_secret_access_key=SECRET_KEY,
        region_name=S3_REGION,
    )

    response = s3.get_object(Bucket=BUCKET, Key=OBJECT_KEY)
    body = response["Body"]

    import io

    text_stream = io.TextIOWrapper(body, encoding="utf-8-sig", newline="")
    reader = csv.DictReader(text_stream, delimiter=";")

    total_counts = Counter()
    chunk = []

    for row in reader:
        chunk.append(row)

        if len(chunk) >= CHUNK_SIZE:
            total_counts.update(count_combinations(chunk))
            chunk.clear()

    if chunk:
        total_counts.update(count_combinations(chunk))

    return total_counts


def sql_string(value):
    return "'" + value.replace("'", "''") + "'"


def duckdb_counts():
    connection = duckdb.connect()

    connection.execute("INSTALL httpfs")
    connection.execute("LOAD httpfs")

    connection.execute(
        f"""
        CREATE OR REPLACE SECRET rustfs_secret (
            TYPE s3,
            KEY_ID {sql_string(ACCESS_KEY)},
            SECRET {sql_string(SECRET_KEY)},
            REGION {sql_string(S3_REGION)},
            ENDPOINT {sql_string(S3_ENDPOINT)},
            URL_STYLE 'path',
            USE_SSL false
        )
        """
    )

    query = f"""
        WITH source AS (
            SELECT
                row_number() OVER () AS row_id,
                key_skills
            FROM read_csv(
                {sql_string(S3_URI)},
                header = true,
                all_varchar = true,
                encoding = 'utf-8'
            )
        ),
        skills AS (
            SELECT DISTINCT
                source.row_id,
                lower(trim(skill_item)) AS skill
            FROM source,
            UNNEST(string_split(coalesce(source.key_skills, ''), ';'))
                AS skill_list(skill_item)
            WHERE trim(skill_item) <> ''
        ),
        counts AS (
            SELECT
                1 AS size,
                skill AS combination,
                count(*) AS frequency
            FROM skills
            GROUP BY skill

            UNION ALL

            SELECT
                2 AS size,
                first_skill.skill || '; ' || second_skill.skill AS combination,
                count(*) AS frequency
            FROM skills AS first_skill
            JOIN skills AS second_skill
                ON first_skill.row_id = second_skill.row_id
                AND first_skill.skill < second_skill.skill
            GROUP BY combination

            UNION ALL

            SELECT
                3 AS size,
                first_skill.skill || '; '
                    || second_skill.skill || '; '
                    || third_skill.skill AS combination,
                count(*) AS frequency
            FROM skills AS first_skill
            JOIN skills AS second_skill
                ON first_skill.row_id = second_skill.row_id
                AND first_skill.skill < second_skill.skill
            JOIN skills AS third_skill
                ON first_skill.row_id = third_skill.row_id
                AND second_skill.skill < third_skill.skill
            GROUP BY combination
        )
        SELECT size, combination, frequency
        FROM counts
        ORDER BY size, frequency DESC, combination
    """

    rows = connection.execute(query).fetchall()
    connection.close()

    return {
        (tuple(part.strip() for part in combination.split("; "))): frequency
        for size, combination, frequency in rows
    }


def save_counts(filename, counts):
    with open(RESULTS_DIR / filename, "w", encoding="utf-8-sig", newline="") as file:
        writer = csv.writer(file, delimiter=";")
        writer.writerow(["type", "combination", "frequency"])

        for combination, frequency in sorted(
            counts.items(),
            key=lambda item: (len(item[0]), -item[1], item[0]),
        ):
            writer.writerow([
                len(combination),
                "; ".join(combination),
                frequency,
            ])


def main():
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    mapreduce_result = mapreduce_counts()
    duckdb_result = duckdb_counts()

    save_counts("mapreduce_counts.csv", mapreduce_result)
    save_counts("duckdb_counts.csv", duckdb_result)

    print(f"MapReduce: {len(mapreduce_result)} комбинаций")
    print(f"DuckDB: {len(duckdb_result)} комбинаций")
    print(f"Результаты сохранены в {RESULTS_DIR}")


if __name__ == "__main__":
    main()