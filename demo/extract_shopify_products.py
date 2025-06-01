import shopify
import os
import sys
import json
import re
from dotenv import load_dotenv
from urllib.parse import urljoin
import logging

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

load_dotenv()

SHOP_URL = os.environ.get("SHOP_URL")
SHOPIFY_ACCESS_TOKEN = os.environ.get("SHOPIFY_ACCESS_TOKEN")
API_VERSION = os.environ.get("SHOPIFY_API_VERSION", '2024-04')
OUTPUT_FILE = os.environ.get("OUTPUT_FILE", "shopify_products.json")

DEMO_STORE_DISCLAIMER_PATTERNS = [
    r"<em>\s*This is a demonstration store\. You can purchase products like this from\s*<a[^>]*href=\"https?://www\.purefixcycles\.com\"[^>]*target=\"_blank\">Pure Fix Cycles</a>\s*</em>",
    r"<!--\s*DEMO_STORE_DISCLAIMER\s*-->",
    r"<div\s+class=['\"]demo-store-disclaimer['\"][^>]*>.*?</div>"
]


def get_all_shopify_products(shop_url, access_token, api_version):
    """
    Fetches all Shopify products with optimized collection loading
    """
    if not shop_url or not access_token:
        logger.error("Error: SHOP_URL and SHOPIFY_ACCESS_TOKEN are required.")
        return None

    session = None
    try:
        session = shopify.Session(shop_url, api_version, access_token)
        shopify.ShopifyResource.activate_session(session)

        logger.info(
            f"Connecting to {shop_url} (API version: {api_version})...")
        logger.info("Fetching products...")

        products = shopify.Product.find(
            fields="id,title,handle,body_html,product_type,vendor,tags,"
                   "published_at,updated_at,images,variants"
        )

        logger.info(f"Found {len(products)} products.")
        return products

    except shopify.ForbiddenError:
        logger.error("Authentication failed or insufficient permissions.")
    except shopify.ResourceNotFound:
        logger.error("Resource not found. Check Shopify URL or API version.")
    except shopify.Unauthorized:
        logger.error("Unauthorized access. Check SHOPIFY_ACCESS_TOKEN.")
    except shopify.ServerError as e:
        logger.error(f"Shopify server error: {e}")
    except Exception as e:
        logger.exception(f"Unexpected error during Shopify API call: {e}")
    finally:
        if session:
            shopify.ShopifyResource.clear_session()
    return None


def clean_description(html_content):
    if not html_content:
        return ""

    for pattern in DEMO_STORE_DISCLAIMER_PATTERNS:
        html_content = re.sub(pattern, "", html_content,
                              flags=re.IGNORECASE | re.DOTALL)

    html_content = re.sub(r'<p>\s*</p>', '', html_content)
    return html_content.strip()


def convert_shopify_product_to_schema_product(product: shopify.Product, shop_url: str) -> dict:
    product_url = urljoin(f"https://{shop_url}", f"/products/{product.handle}")

    cleaned_description = clean_description(product.body_html)

    product_info = {
        "@type": "Product",
        "name": product.title,
        "description": cleaned_description,
        "url": product_url,
        "productID": str(product.id),
        "vendor": product.vendor,
        "productType": product.product_type,
        "tags": product.tags,
        "publishedAt": product.published_at,
        "updatedAt": product.updated_at,
    }

    # Add images
    if product.images:
        product_info["primaryImage"] = product.images[0].src
        product_info["images"] = [img.src for img in product.images]

    # Add variants
    if product.variants:
        variants_info = []
        for variant in product.variants:
            variant_info = {
                "@type": "ProductVariant",
                "id": str(variant.id),
                "title": variant.title,
                "price": variant.price,
                "sku": variant.sku,
                "inventoryQuantity": getattr(variant, 'inventory_quantity', 0),
            }
            variants_info.append(variant_info)
        product_info["variants"] = variants_info

    return {k: v for k, v in product_info.items() if v is not None}


def main():
    logger.info("Starting Shopify product export")

    if not SHOP_URL or not SHOPIFY_ACCESS_TOKEN:
        logger.error("SHOP_URL and SHOPIFY_ACCESS_TOKEN must be set.")
        sys.exit(1)

    # Get products
    products = get_all_shopify_products(
        SHOP_URL, SHOPIFY_ACCESS_TOKEN, API_VERSION)

    if products is None:
        logger.error("Failed to retrieve products. Exiting.")
        sys.exit(1)

    if not products:
        logger.info("No products found. Exiting.")
        sys.exit(0)

    # Convert and write products to JSONL file
    try:
        with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
            for product in products:
                try:
                    product_data = convert_shopify_product_to_schema_product(
                        product, SHOP_URL)
                    # Write each product as a separate JSON line
                    json_line = json.dumps(product_data, ensure_ascii=False)
                    f.write(json_line + '\n')
                except Exception as e:
                    logger.error(
                        f"Error processing product {product.id}: {str(e)}")

        logger.info(
            f"Successfully exported {len(products)} products to {OUTPUT_FILE}")

    except Exception as e:
        logger.exception(f"Fatal error during export: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
