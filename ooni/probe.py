import requests
import csv
import re
import logging
from datetime import datetime, timedelta

logging.basicConfig(
    level=logging.NOTSET,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("ooni_domain_fetch.log", mode="a"),
        logging.StreamHandler(),
    ],
)


def normalize_domain(domain):
    return domain.lstrip("www.") if domain.startswith("www.") else domain


def main(output_file=None, country=None, day_range=7):
    try:
        today = datetime.now()
        since = (today - timedelta(days=day_range)).strftime("%Y-%m-%d")
        until = today.strftime("%Y-%m-%d")

        base_url = "https://api.ooni.io/api/v1/aggregation"
        params = {
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
        if response.status_code != 200:
            logging.error(
                f"Failed to download data from OONI API, status code: {response.status_code}"
            )
            return
        logging.info("Successfully downloaded data from OONI API")

        domains = set()
        csv_data = response.content.decode("utf-8").splitlines()
        csv_reader = csv.DictReader(csv_data)

        # Pattern to match incorrect domains
        pattern = r"^.*\.{2,}.*$"

        for row in csv_reader:
            domain = row["domain"].strip()
            anomaly_count = int(row["anomaly_count"])
            ok_count = int(row["ok_count"])

            # Log domain processing details
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
                    logging.info(
                        f"Anomaly rate is high for the domain: {normalized_domain} - Adding to the list"
                    )
            else:
                logging.info(f"Site is accessible in Myanmar: {domain}")

        # Write the domains to the output file
        with open(output_file, "w") as output:
            for domain in sorted(domains):  # Optionally sort the domains
                output.write(f"{domain}\n")

        logging.info(f"Total unique domains written to {output_file}: {len(domains)}")

    except Exception as e:
        logging.error(f"Error occurred during fetching or processing: {e}")


if __name__ == "__main__":
    output_file = "ooni/domains.lst"
    country = "MM"
    day_range = 14
    main(output_file=output_file, country=country, day_range=day_range)
