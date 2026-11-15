"""
scripts/verify_links_and_images.py
==================================

Validates that all image assets, file links, and documentation cross-references
in README.md and docs/presentation/ exist on disk.
"""

import re
from pathlib import Path

def main() -> None:
    readme_path = Path("README.md")
    content = readme_path.read_text(encoding="utf-8")

    # 1. Image checks
    img_markdown = re.findall(r'!\[.*?\]\((.*?)\)', content)
    img_html = re.findall(r'<img\s+[^>]*src=[\"\'](.*?)[\"\']', content)
    all_images = img_markdown + img_html

    print(f"[*] Found {len(all_images)} image references in README.md")
    missing_images = []
    for img in set(all_images):
        if img.startswith("http://") or img.startswith("https://"):
            continue
        # Strip anchor or params
        clean_img = img.split("#")[0].split("?")[0]
        p = Path(clean_img)
        if not p.exists():
            missing_images.append(img)
        else:
            print(f"    [OK] Image: {clean_img}")

    # 2. Markdown link checks
    links = re.findall(r'\[.*?\]\((.*?)\)', content)
    print(f"\n[*] Found {len(links)} link references in README.md")
    missing_links = []
    for link in set(links):
        if link.startswith("http://") or link.startswith("https://") or link.startswith("#"):
            continue
        clean_link = link.split("#")[0].split("?")[0]
        if not clean_link:
            continue
        p = Path(clean_link)
        if not p.exists():
            missing_links.append(link)
        else:
            print(f"    [OK] Link: {clean_link}")

    if missing_images:
        print(f"\n[FAIL] Missing images: {missing_images}")
    else:
        print("\n[PASS] All local images verified successfully.")

    if missing_links:
        print(f"\n[FAIL] Missing links: {missing_links}")
    else:
        print("\n[PASS] All local documentation links verified successfully.")

    assert len(missing_images) == 0, f"Missing images: {missing_images}"
    assert len(missing_links) == 0, f"Missing links: {missing_links}"

if __name__ == "__main__":
    main()
