import csv
import logging

logger = logging.getLogger(__name__)


class CSVWriter:
    def __init__(self, filename, fieldnames):
        self.filename = filename
        self.fieldnames = fieldnames
        logger.info(f"fieldnames: {self.fieldnames}")

    def write_transactions(self, transactions):
        # Clear the file before writing
        open(self.filename, "w").close()

        with open(self.filename, mode="w", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=self.fieldnames)
            writer.writeheader()
            for transaction in transactions:
                writer.writerow(transaction.writer_to_dict())
