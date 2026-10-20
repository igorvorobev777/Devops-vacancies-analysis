import csv
from pathlib import Path


RESULTS_DIR = Path(r"D:\rustfs\results")
MAPREDUCE_FILE = RESULTS_DIR / "mapreduce_counts.csv"
DUCKDB_FILE = RESULTS_DIR / "duckdb_counts.csv"
DIFFERENCES_FILE = RESULTS_DIR / "verification_differences.csv"


def read_counts(filename):
    counts = {}

    with open(filename, "r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file, delimiter=";")

        for row in reader:
            key = (row["type"], row["combination"])
            counts[key] = int(row["frequency"])

    return counts


def main():
    mapreduce_counts = read_counts(MAPREDUCE_FILE)
    duckdb_counts = read_counts(DUCKDB_FILE)

    all_combinations = set(mapreduce_counts) | set(duckdb_counts)
    differences = []

    for key in sorted(all_combinations):
        mapreduce_frequency = mapreduce_counts.get(key, 0)
        duckdb_frequency = duckdb_counts.get(key, 0)

        if mapreduce_frequency != duckdb_frequency:
            differences.append(
                (
                    key[0],
                    key[1],
                    mapreduce_frequency,
                    duckdb_frequency,
                )
            )

    with open(DIFFERENCES_FILE, "w", encoding="utf-8-sig", newline="") as file:
        writer = csv.writer(file, delimiter=";")
        writer.writerow([
            "type",
            "combination",
            "mapreduce_frequency",
            "duckdb_frequency",
        ])
        writer.writerows(differences)

    if differences:
        print(f"Результаты не совпадают. Расхождений: {len(differences)}")
        print(f"Подробности: {DIFFERENCES_FILE}")
        raise SystemExit(1)

    print("Результаты MapReduce и DuckDB полностью совпадают.")
    print(f"Сравнено комбинаций: {len(all_combinations)}")


if __name__ == "__main__":
    main()