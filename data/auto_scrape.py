import csv
import os
import time
import random
import undetected_chromedriver as uc
import logging

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup

from parse_nutritionv2 import body_to_json


FAILED_CSV = "failed_urls.csv"


def initialize_failed_csv():
    if not os.path.exists(FAILED_CSV) or os.path.getsize(FAILED_CSV) == 0:
        with open(FAILED_CSV, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["page number", "count", "url"])


def record_failed_url(page_number, count, url):
    with open(FAILED_CSV, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([page_number, count, url])


def extract_product_links(html, base_url="https://www.nofrills.ca"):
    soup = BeautifulSoup(html, "html.parser")
    links = set()

    for a in soup.find_all("a", href=True):
        href = a["href"]

        if "/p/" in href:
            full_url = href if href.startswith("http") else base_url + href
            links.add(full_url)

    return sorted(links)


def url_to_json_with_retry(
    url,
    driver,
    page_number,
    count,
    attempts=3,
    base_timeout=10
):
    for attempt in range(1, attempts + 1):
        timeout = base_timeout * attempt + random.randint(7, 10)

        try:
            driver.get(url)

            WebDriverWait(driver, timeout).until(
                EC.presence_of_element_located(
                    (By.CLASS_NAME, "product-name__item--name")
                )
            )

            time.sleep(random.randint(6, 10))

            body_html = driver.find_element(
                By.TAG_NAME,
                "body"
            ).get_attribute("innerHTML")

            body_to_json(body_html)

            return True

        except Exception as e:
            print(
                f"Attempt {attempt}/{attempts} failed for {url} "
                f"({timeout}s): {type(e).__name__}"
            )
            time.sleep(2)

    record_failed_url(page_number, count, url)
    return False


def wait_for_products_stable(
    driver,
    selector='[data-testid="product-title"]',
    timeout=20,
    stable_checks=3,
    poll=0.5
):
    end_time = time.time() + timeout
    last_count = -1
    stable_count = 0

    while time.time() < end_time:
        count = len(driver.find_elements(By.CSS_SELECTOR, selector))

        if count > 0 and count == last_count:
            stable_count += 1

            if stable_count >= stable_checks:
                return count
        else:
            stable_count = 0

        last_count = count
        time.sleep(poll)

    return last_count


def get_links(page_url, driver):
    driver.get(page_url)

    wait_for_products_stable(driver)

    body_html = driver.find_element(
        By.TAG_NAME,
        "body"
    ).get_attribute("innerHTML")

    return extract_product_links(body_html)


if __name__ == "__main__":
    driver = None
    success = 0
    failed_csv_initialized = False

    logging.basicConfig(
        filename="logs.txt",
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s"
    )

    try:
        initialize_failed_csv()

        for page_number in range(87, 210):
            page_url = (
                "https://www.nofrills.ca/en/food/c/27985"
                f"?page={page_number}"
            )

            driver = uc.Chrome(
                headless=False,
                use_subprocess=False,
                version_main=152
            )

            links = get_links(page_url, driver)

            detail = f"Read Page {page_number} with {len(links)} items."
            logging.info(detail)
            print(detail)

            count = 0

            for url in links:
                if count % 20 == 0:
                    if driver is not None:
                        driver.quit()

                    driver = uc.Chrome(
                        headless=False,
                        use_subprocess=False,
                        version_main=152
                    )

                count += 1

                result = url_to_json_with_retry(
                    url=url,
                    driver=driver,
                    page_number=page_number,
                    count=count
                )

                if result:
                    success += 1

                detail = f"[PAGE #{page_number}] [Item: {count}/{len(links)}]"
                logging.info(detail)
                print(detail)

            driver.quit()

    finally:
        if driver is not None:
            driver.quit()

        print(f"Successful counts: {success}")