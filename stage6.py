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
TOP_SKILLS = 15


def sql_string(value):
    return "'" + value.replace("'", "''") + "'"


def save_csv(filename, header, rows):
    path = RESULTS_DIR / filename

    with open(path, "w", encoding="utf-8-sig", newline="") as file:
        writer = csv.writer(file, delimiter=";")
        writer.writerow(header)
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

    base_ctes = f"""
        WITH source AS (
            SELECT
                row_number() OVER () AS row_id,
                area,
                experience,
                currency,
                salary_from,
                salary_to,
                key_skills
            FROM read_csv(
                {sql_string(S3_URI)},
                header = true,
                all_varchar = true,
                encoding = 'utf-8'
            )
        ),
        normalized AS (
            SELECT
                row_id,
                CASE
                    WHEN lower(coalesce(area, '')) LIKE '%москва%'
                      OR lower(coalesce(area, '')) LIKE '%moscow%'
                        THEN 'Москва'
                    WHEN lower(coalesce(area, '')) LIKE '%санкт-петербург%'
                      OR lower(coalesce(area, '')) LIKE '%петербург%'
                      OR lower(coalesce(area, '')) LIKE '%saint petersburg%'
                      OR lower(coalesce(area, '')) LIKE '%спб%'
                        THEN 'Санкт-Петербург'
                    WHEN lower(coalesce(area, '')) LIKE '%новосибирск%'
                      OR lower(coalesce(area, '')) LIKE '%novosibirsk%'
                        THEN 'Новосибирск'
                END AS region,
                trim(experience) AS experience,
                upper(trim(currency)) AS currency,
                try_cast(
                    replace(replace(trim(salary_from), ' ', ''), ',', '.')
                    AS DOUBLE
                ) AS salary_from_value,
                try_cast(
                    replace(replace(trim(salary_to), ' ', ''), ',', '.')
                    AS DOUBLE
                ) AS salary_to_value,
                key_skills
            FROM source
        ),
        vacancies AS (
            SELECT
                row_id,
                region,
                experience,
                key_skills,
                CASE
                    WHEN currency IN ('RUR', 'RUB') THEN
                        CASE
                            WHEN salary_from_value IS NOT NULL
                                 AND salary_to_value IS NOT NULL
                                THEN (salary_from_value + salary_to_value) / 2
                            WHEN salary_from_value IS NOT NULL
                                THEN salary_from_value
                            ELSE salary_to_value
                        END
                END AS salary
            FROM normalized
            WHERE region IS NOT NULL
        )
    """

    summary_query = base_ctes + """
        SELECT
            region,
            count(*) AS vacancies,
            count(salary) AS vacancies_with_salary,
            round(median(salary), 2) AS median_salary
        FROM vacancies
        GROUP BY region
        ORDER BY region
    """

    experience_query = base_ctes + """
        SELECT
            region,
            experience,
            count(*) AS vacancies,
            count(salary) AS vacancies_with_salary,
            round(median(salary), 2) AS median_salary
        FROM vacancies
        WHERE experience IS NOT NULL AND experience <> ''
        GROUP BY region, experience
        ORDER BY region, experience
    """

    skills_query = base_ctes + f""",
        skills AS (
            SELECT DISTINCT
                vacancies.row_id,
                vacancies.region,
                vacancies.salary,
                lower(trim(skill_item)) AS skill
            FROM vacancies
            CROSS JOIN UNNEST(
                string_split(coalesce(vacancies.key_skills, ''), ';')
            ) AS parsed_skills(skill_item)
            WHERE trim(skill_item) <> ''
        ),
        region_totals AS (
            SELECT region, count(*) AS total_vacancies
            FROM vacancies
            GROUP BY region
        ),
        skill_stats AS (
            SELECT
                region,
                skill,
                count(*) AS vacancies_with_skill,
                count(salary) AS salary_vacancies,
                round(median(salary), 2) AS median_salary
            FROM skills
            GROUP BY region, skill
        ),
        ranked_skills AS (
            SELECT
                skill_stats.region,
                skill_stats.skill,
                skill_stats.vacancies_with_skill,
                round(
                    100.0 * skill_stats.vacancies_with_skill
                    / region_totals.total_vacancies,
                    2
                ) AS demand_percent,
                skill_stats.salary_vacancies,
                skill_stats.median_salary,
                row_number() OVER (
                    PARTITION BY skill_stats.region
                    ORDER BY
                        skill_stats.vacancies_with_skill DESC,
                        skill_stats.skill
                ) AS skill_rank
            FROM skill_stats
            JOIN region_totals USING (region)
        )
        SELECT
            region,
            skill,
            vacancies_with_skill,
            demand_percent,
            salary_vacancies,
            median_salary
        FROM ranked_skills
        WHERE skill_rank <= {TOP_SKILLS}
        ORDER BY region, skill_rank
    """

    summary_rows = connection.execute(summary_query).fetchall()
    experience_rows = connection.execute(experience_query).fetchall()

    raw_skills_rows = connection.execute(skills_query).fetchall()
    skills_rows = [
        (
            region,
            skill,
            vacancies_with_skill,
            f"{demand_percent:.2f}".replace(".", ","),
            salary_vacancies,
            median_salary,
        )
        for (
            region,
            skill,
            vacancies_with_skill,
            demand_percent,
            salary_vacancies,
            median_salary,
        ) in raw_skills_rows
    ]

    connection.close()

    save_csv(
        "stage6_region_summary.csv",
        [
            "region",
            "vacancies",
            "vacancies_with_salary",
            "median_salary_rub",
        ],
        summary_rows,
    )

    save_csv(
        "stage6_salary_by_experience.csv",
        [
            "region",
            "experience",
            "vacancies",
            "vacancies_with_salary",
            "median_salary_rub",
        ],
        experience_rows,
    )

    save_csv(
        "stage6_top_skills.csv",
        [
            "region",
            "skill",
            "vacancies_with_skill",
            "demand_percent",
            "salary_vacancies",
            "median_salary_rub",
        ],
        skills_rows,
    )

    print(f"Сводка по регионам: {RESULTS_DIR / 'stage6_region_summary.csv'}")
    print(f"Зарплаты по опыту: {RESULTS_DIR / 'stage6_salary_by_experience.csv'}")
    print(f"Востребованные навыки: {RESULTS_DIR / 'stage6_top_skills.csv'}")


if __name__ == "__main__":
    main()