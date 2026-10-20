import csv
import os
from pathlib import Path

import duckdb


BUCKET = "hh-lake"
OBJECT_KEY = "devops_vacancies.csv"
S3_URI = f"s3://{BUCKET}/{OBJECT_KEY}"

S3_ENDPOINT = "localhost:9000"
S3_REGION = "us-east-1"
ACCESS_KEY = os.environ["RUSTFS_ACCESS_KEY"]
SECRET_KEY = os.environ["RUSTFS_SECRET_KEY"]

RESULTS_DIR = Path(r"D:\rustfs\results")
MIN_VACANCIES = 10


def sql_string(value):
    return "'" + value.replace("'", "''") + "'"


def save_csv(filename, rows):
    path = RESULTS_DIR / filename

    with open(path, "w", encoding="utf-8-sig", newline="") as file:
        writer = csv.writer(file, delimiter=";")
        writer.writerow([
            "experience",
            "type",
            "combination",
            "vacancies",
            "median_salary",
        ])
        writer.writerows(rows)


def main():
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

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
                salary_from,
                salary_to,
                currency,
                experience,
                key_skills
            FROM read_csv(
                {sql_string(S3_URI)},
                header = true,
                all_varchar = true,
                encoding = 'utf-8'
            )
        ),
        salary_values AS (
            SELECT
                row_id,
                experience,
                key_skills,
                upper(trim(currency)) AS currency,
                try_cast(
                    replace(replace(trim(salary_from), ' ', ''), ',', '.')
                    AS DOUBLE
                ) AS salary_from_value,
                try_cast(
                    replace(replace(trim(salary_to), ' ', ''), ',', '.')
                    AS DOUBLE
                ) AS salary_to_value
            FROM source
        ),
        salary_rows AS (
            SELECT
                row_id,
                experience,
                key_skills,
                CASE
                    WHEN salary_from_value IS NOT NULL
                         AND salary_to_value IS NOT NULL
                        THEN (salary_from_value + salary_to_value) / 2
                    WHEN salary_from_value IS NOT NULL
                        THEN salary_from_value
                    ELSE salary_to_value
                END AS salary
            FROM salary_values
            WHERE currency IN ('RUR', 'RUB')
        ),
        skills AS (
            SELECT DISTINCT
                salary_rows.row_id,
                salary_rows.experience,
                salary_rows.salary,
                lower(trim(skill_item)) AS skill
            FROM salary_rows,
            UNNEST(string_split(coalesce(salary_rows.key_skills, ''), ';'))
                AS skill_list(skill_item)
            WHERE salary_rows.salary IS NOT NULL
              AND trim(skill_item) <> ''
        ),
        combinations AS (
            SELECT
                first_skill.experience,
                2 AS type,
                first_skill.skill || '; ' || second_skill.skill AS combination,
                count(*) AS vacancies,
                median(first_skill.salary) AS median_salary
            FROM skills AS first_skill
            JOIN skills AS second_skill
                ON first_skill.row_id = second_skill.row_id
                AND first_skill.skill < second_skill.skill
            GROUP BY first_skill.experience, combination

            UNION ALL

            SELECT
                first_skill.experience,
                3 AS type,
                first_skill.skill || '; '
                    || second_skill.skill || '; '
                    || third_skill.skill AS combination,
                count(*) AS vacancies,
                median(first_skill.salary) AS median_salary
            FROM skills AS first_skill
            JOIN skills AS second_skill
                ON first_skill.row_id = second_skill.row_id
                AND first_skill.skill < second_skill.skill
            JOIN skills AS third_skill
                ON first_skill.row_id = third_skill.row_id
                AND second_skill.skill < third_skill.skill
            GROUP BY first_skill.experience, combination
        )
        SELECT experience, type, combination, vacancies, median_salary
        FROM combinations
        WHERE vacancies >= ?
        ORDER BY experience, type, median_salary DESC, combination
    """

    result = connection.execute(query, [MIN_VACANCIES]).fetchall()
    connection.close()

    rows = [
        (
            experience,
            skill_count,
            combination,
            vacancies,
            round(median_salary, 2),
        )
        for experience, skill_count, combination, vacancies, median_salary in result
    ]

    pair_rows = [row for row in rows if row[1] == 2]
    triple_rows = [row for row in rows if row[1] == 3]

    save_csv("skills_salary_all.csv", rows)
    save_csv("skills_salary_pairs.csv", pair_rows)
    save_csv("skills_salary_triples.csv", triple_rows)

    print(f"Пары навыков: {len(pair_rows)}")
    print(f"Тройки навыков: {len(triple_rows)}")
    print(f"Минимум вакансий на комбинацию внутри группы: {MIN_VACANCIES}")
    print(f"Результаты сохранены в {RESULTS_DIR}")


if __name__ == "__main__":
    main()