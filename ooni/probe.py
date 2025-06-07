from typing import Set
import requests
import csv
import re
import logging
from datetime import datetime, timedelta
import argparse

logging.basicConfig(
    level=logging.NOTSET,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("probe.log", mode="a"),
        logging.StreamHandler(),
    ],
)


def normalize_domain(domain: str) -> str:
    return domain.lstrip("www.") if domain.startswith("www.") else domain


def get_domains_from_ooni_api(
    country: str,
    day_range: int,
    verbose: bool = False,
) -> Set[str] | None:
    try:
        today = datetime.now()
        since = (today - timedelta(days=day_range)).strftime("%Y-%m-%d")
        until = today.strftime("%Y-%m-%d")

        base_url = "https://api.ooni.io/api/v1/aggregation"
        params: dict[str, str | None] = {
            "axis_y": "domain",
            "axis_x": "measurement_start_day",
            "probe_cc": country,
            "since": since,
            "until": until,
            "test_name": "web_connectivity",
            "time_grain": "day",
            "format": "CSV",
        }

        url = f"{base_url}?{'&'.join([f'{k}={v}' for k, v in params.items()])}"
        response = requests.get(url)
        response.raise_for_status()  # Raise an error for bad responses
        logging.info("Successfully downloaded data from OONI API")

        domains: Set[str] = set()
        csv_data = response.content.decode("utf-8").splitlines()
        csv_reader = csv.DictReader(csv_data)

        # Pattern to match incorrect domains
        pattern = r"^.*\.{2,}.*$"

        for row in csv_reader:
            domain = row["domain"].strip()
            anomaly_count = int(row["anomaly_count"])
            ok_count = int(row["ok_count"])

            # Log domain processing details
            if verbose:
                logging.info(
                    f"Checking domain: {domain} | Anomalies: {anomaly_count}, OK: {ok_count}, Anomaly Rate: {anomaly_count / (anomaly_count + ok_count) if (anomaly_count + ok_count) > 0 else 0:.2f}"
                )

            # Filter out incorrect domains
            if re.match(pattern, domain):
                logging.error(f"Domain is either incorrectly formatted: {domain}")
                # But...
                continue

            # Log and process based on anomaly vs OK count
            if anomaly_count > ok_count:
                normalized_domain = normalize_domain(domain)
                if normalized_domain not in domains:
                    domains.add(normalized_domain)
                    if verbose:
                        logging.info(
                            f"Anomaly rate is high for the domain: {normalized_domain} - Adding to the list"
                        )
            else:
                if verbose:
                    logging.info(f"Site is accessible in {country}: {domain}")

    except Exception as e:
        logging.error(f"An error occurred while processing the data: {e}")
        return set("")


def main():
    parser = argparse.ArgumentParser(description="Probe Parser for OONI Data")
    parser.add_argument("--input", "-i", default=None, help="Input file path")
    parser.add_argument("--output", "-o", required=True, help="Output file path")
    parser.add_argument("--country", "-c", default="MM", help="Country code")
    parser.add_argument("--day-range", "-dr", default=14, help="Day range for data")
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Enable verbose output"
    )

    args = parser.parse_args()

    output_file = args.output
    verbose = args.verbose

    try:
        if args.input:
            # Read domains from the input file if provided
            with open(args.input, "r") as input_file:
                domains = set(line.strip() for line in input_file if line.strip())
                logging.info(f"Read {len(domains)} domains from input file.")
        else:
            # Fetch domains from OONI API with country and day range
            country = args.country
            day_range = int(args.day_range)
            domains = get_domains_from_ooni_api(country, day_range, verbose)

        # Write the domains to the output file
        if domains:
            with open(output_file, "w") as output:
                for domain in sorted(domains):  # Optionally sort the domains
                    output.write(f"{domain}\n")

            logging.info(
                f"Total unique domains written to {output_file}: {len(domains)}"
            )
        else:
            logging.warning("No domains found.")

    except Exception as e:
        logging.error(f"Error: {e}")


if __name__ == "__main__":
    main()
