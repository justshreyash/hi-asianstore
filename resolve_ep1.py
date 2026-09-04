#!/usr/bin/env python3
"""
Episode 1 Direct Download Resolver

Extracts direct download URLs for Episode 1 from KDramaLover:
- HubCloud Priority: Download [FSL Server] & Download [Server : 10Gbps]
- GDFlix Priority: INSTANT DL [10GBPS] & CLOUD DOWNLOAD [R2]
"""

import sys
import os
import re
import json
import argparse
import urllib.parse
from bs4 import BeautifulSoup
from curl_cffi import requests as cureq

# Ensure UTF-8 output across Windows consoles
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except AttributeError:
        pass

DEFAULT_DRAMA_URL = "https://kdramalover.com/filing-for-love-korean-drama-hindi-dubbed/"

GDFLIX_WORKING_MIRRORS = [
    "https://gdflix.dev",
    "https://new3.gdflix.io"
]


class LinkResolver:
    def __init__(self):
        self.session = cureq.Session(impersonate="chrome124")

    def get_target_archive_url(self, drama_url: str, quality: str = "1080p") -> tuple[str, str]:
        """Fetch drama page and locate single episode archive URL (ignoring zip). Prefers 1080p, falls back to 720p or 480p."""
        r = self.session.get(drama_url, timeout=20)
        soup = BeautifulSoup(r.text, "html.parser")

        # Priority order: preferred quality first, then 720p, 480p, or any non-zip single episode
        qualities_to_try = [quality.lower().strip()]
        for q in ["720p", "480p", "1080p"]:
            if q not in qualities_to_try:
                qualities_to_try.append(q)

        for q in qualities_to_try:
            candidates = []
            for a in soup.find_all("a", href=True):
                href = a["href"].strip()
                text = a.get_text(strip=True)
                text_lower = text.lower()

                if "zip" in text_lower or "zip" in href.lower():
                    continue

                if q in text_lower and ("single" in text_lower or "episode" in text_lower):
                    candidates.append((text, href))

            if not candidates:
                for a in soup.find_all("a", href=True):
                    href = a["href"].strip()
                    text = a.get_text(strip=True)
                    if "zip" not in text.lower() and q in text.lower() and href.startswith("http"):
                        candidates.append((text, href))

            if candidates:
                for text, href in candidates:
                    if "single" in text.lower() and "episode" in text.lower():
                        return text, href
                return candidates[0]

        # Last resort: any non-zip link containing single/episode
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            text = a.get_text(strip=True)
            text_lower = text.lower()
            if "zip" not in text_lower and ("single" in text_lower or "episode" in text_lower) and href.startswith("http"):
                return text, href

        raise ValueError(f"No single episode links found (only zip or empty) on {drama_url}")

    def get_episode_1_links(self, archive_url: str) -> dict[str, str]:
        """Extract HubCloud and GDFlix links for Episode 1 from archive page."""
        r = self.session.get(archive_url, timeout=20)
        
        # Check for HubCloud Pack page
        if "packData" in r.text and "drive/packs" in archive_url:
            try:
                marker = "const packData = JSON.parse("
                p1 = r.text.find(marker)
                if p1 != -1:
                    p_quote = r.text.find("{", p1)
                    pack_json, _ = json.JSONDecoder().raw_decode(r.text[p_quote:])
                    files = pack_json.get("files", [])
                    if files and files[0].get("share_id"):
                        return {"hubcloud": f"https://hubcloud.cx/drive/{files[0]['share_id']}"}
            except Exception:
                pass

        # Check for GDFlix Pack page
        if "/pack/" in archive_url and ("gdflix" in archive_url or "GDFlix" in r.text):
            try:
                pack_soup = BeautifulSoup(r.text, "html.parser")
                base_origin = archive_url.split("/pack/")[0]
                for a in pack_soup.find_all("a", href=True):
                    href = a["href"].strip()
                    if "/file/" in href:
                        full_href = href if href.startswith("http") else f"{base_origin}{href}"
                        return {"gdflix": full_href}
            except Exception:
                pass

        soup = BeautifulSoup(r.text, "html.parser")
        content = soup.find("div", class_="entry-content") or soup.find("article") or soup.body

        ep1_links = {}
        in_ep1 = False

        for elem in content.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "p", "div", "li"]):
            text = elem.get_text(" ", strip=True)

            # Look for Episode 01 / Ep01 header
            if re.search(r"\b(ep\s*0?1|episode\s*0?1)\b", text, re.IGNORECASE):
                if not elem.find("a"):
                    in_ep1 = True
                    continue

            # If we reached Episode 02, stop looking for Ep 1 links
            if in_ep1 and re.search(r"\b(ep\s*0?2|episode\s*0?2)\b", text, re.IGNORECASE):
                if not elem.find("a"):
                    break

            if in_ep1:
                for a in elem.find_all("a", href=True):
                    href = a["href"].strip()
                    if "hubcloud" in href.lower() and "hubcloud" not in ep1_links:
                        ep1_links["hubcloud"] = href
                    elif "gdflix" in href.lower() and "gdflix" not in ep1_links:
                        ep1_links["gdflix"] = href

        # If strict Ep1 header wasn't found, fallback to first occurrence of each host
        if not ep1_links:
            for a in content.find_all("a", href=True):
                href = a["href"].strip()
                if "hubcloud" in href.lower() and "hubcloud" not in ep1_links:
                    ep1_links["hubcloud"] = href
                elif "gdflix" in href.lower() and "gdflix" not in ep1_links:
                    ep1_links["gdflix"] = href
                if len(ep1_links) == 2:
                    break

        return ep1_links

    def get_all_episodes(self, archive_url: str) -> list[dict]:
        """
        Extract all structured episodes and their provider links from the archive page.
        Returns a list of dicts:
        [{ 'episode_number': int, 'title': str, 'links': {'hubcloud': str, 'gdflix': str} }, ...]
        """
        r = self.session.get(archive_url, timeout=20)

        # Support HubCloud Drive Packs (JSON embedded in page)
        if "packData" in r.text and ("drive/packs" in archive_url or "packData = JSON.parse" in r.text):
            try:
                marker = "const packData = JSON.parse("
                p1 = r.text.find(marker)
                if p1 != -1:
                    p_quote = r.text.find("{", p1)
                    pack_json, _ = json.JSONDecoder().raw_decode(r.text[p_quote:])
                    files = pack_json.get("files", [])
                    pack_episodes = []
                    for idx, f in enumerate(files, start=1):
                        fname = f.get("file_name", "")
                        share_id = f.get("share_id", "")
                        if not share_id:
                            continue
                        ep_match = re.search(r"\bS\d+E(\d+)\b|\bEp(?:isode)?\s*0?(\d+)\b", fname, re.IGNORECASE)
                        if ep_match:
                            ep_num = int(ep_match.group(1) or ep_match.group(2))
                        else:
                            ep_num = idx
                        pack_episodes.append({
                            "episode_number": ep_num,
                            "title": fname,
                            "links": {
                                "hubcloud": f"https://hubcloud.cx/drive/{share_id}"
                            }
                        })
                    if pack_episodes:
                        pack_episodes.sort(key=lambda x: x["episode_number"])
                        return pack_episodes
            except Exception as e:
                print(f"[!] Warning parsing HubCloud pack data: {e}")

        # Support GDFlix Packs (e.g. https://gdflix.dev/pack/XglakayRV3)
        if "/pack/" in archive_url and ("gdflix" in archive_url or "GDFlix" in r.text):
            try:
                pack_soup = BeautifulSoup(r.text, "html.parser")
                base_origin = archive_url.split("/pack/")[0]
                pack_episodes = []
                for a in pack_soup.find_all("a", href=True):
                    href = a["href"].strip()
                    if "/file/" in href:
                        fname = a.get_text(strip=True)
                        full_href = href if href.startswith("http") else f"{base_origin}{href}"
                        ep_match = re.search(r"\bS\d+E(\d+)\b|\bEp(?:isode)?\s*0?(\d+)\b", fname, re.IGNORECASE)
                        if ep_match:
                            ep_num = int(ep_match.group(1) or ep_match.group(2))
                        else:
                            ep_num = len(pack_episodes) + 1
                        pack_episodes.append({
                            "episode_number": ep_num,
                            "title": fname,
                            "links": {
                                "gdflix": full_href
                            }
                        })
                    elif "hubcloud" in href.lower() and pack_episodes:
                        # Sometimes pack pages also list mirror links
                        pack_episodes[-1]["links"]["hubcloud"] = href
                if pack_episodes:
                    pack_episodes.sort(key=lambda x: x["episode_number"])
                    return pack_episodes
            except Exception as e:
                print(f"[!] Warning parsing GDFlix pack data: {e}")

        soup = BeautifulSoup(r.text, "html.parser")
        content = soup.find("div", class_="entry-content") or soup.find("article") or soup.body

        episodes = []
        current_ep_num = None
        current_ep_title = ""
        current_links = {}

        for elem in content.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "p", "div", "li"]):
            text = elem.get_text(" ", strip=True)

            # Match Ep01, Episode 1, etc.
            ep_match = re.search(r"\b(ep|episode)\s*0?(\d+)\b", text, re.IGNORECASE)
            if ep_match and not elem.find("a"):
                if current_ep_num is not None and current_links:
                    episodes.append({
                        "episode_number": current_ep_num,
                        "title": current_ep_title or f"Episode {current_ep_num}",
                        "links": current_links
                    })
                    current_links = {}
                current_ep_num = int(ep_match.group(2))
                current_ep_title = text
                continue

            for a in elem.find_all("a", href=True):
                href = a["href"].strip()
                if "hubcloud" in href.lower() and "hubcloud" not in current_links:
                    current_links["hubcloud"] = href
                elif "gdflix" in href.lower() and "gdflix" not in current_links:
                    current_links["gdflix"] = href

        # Add the final episode
        if current_ep_num is not None and current_links:
            episodes.append({
                "episode_number": current_ep_num,
                "title": current_ep_title or f"Episode {current_ep_num}",
                "links": current_links
            })

        return episodes

    def resolve_episode_direct_urls(self, episode_links: dict) -> dict[str, str]:
        """
        Given {'hubcloud': '...', 'gdflix': '...'}, resolve direct URLs:
        - 'r2': Cloudflare R2 direct link (best for Vidara)
        - 'google_cdn': Google Video CDN link (best for Byse)
        """
        urls = {}

        if "hubcloud" in episode_links:
            try:
                hc_res = self.resolve_hubcloud(episode_links["hubcloud"])
                for item in hc_res:
                    s_low = item["server"].lower()
                    if ("fsl server" in s_low or "cloudflare worker" in s_low or "workers.dev" in item.get("url", "")) and "r2" not in urls:
                        urls["r2"] = item["url"]
                    if "10gbps" in s_low and "google" in item.get("url", "") and "google_cdn" not in urls:
                        urls["google_cdn"] = item["url"]
            except Exception as e:
                print(f"[!] Warning resolving HubCloud: {e}")

        if "gdflix" in episode_links:
            try:
                gdf_res = self.resolve_gdflix(episode_links["gdflix"])
                for item in gdf_res:
                    s_low = item["server"].lower()
                    if "r2" in s_low and "r2" not in urls:
                        urls["r2"] = item["url"]
                    if "instant dl" in s_low and "google" in item.get("url", "") and "google_cdn" not in urls:
                        urls["google_cdn"] = item["url"]
            except Exception as e:
                print(f"[!] Warning resolving GDFlix: {e}")

        return urls

    def resolve_hubcloud(self, hubcloud_url: str) -> list[dict]:
        """
        Resolve HubCloud page:
        Target priority:
        1. Download [FSL Server] (img 3)
        2. Download [Server : 10Gbps] (img 3)
        """
        r1 = self.session.get(hubcloud_url, timeout=20)
        soup1 = BeautifulSoup(r1.text, "html.parser")

        gen_btn = None
        for a in soup1.find_all("a", href=True):
            if a.get("id") == "download" or "generate direct download link" in a.get_text(strip=True).lower():
                gen_btn = a
                break

        if not gen_btn:
            return []

        gamerx_url = gen_btn["href"]
        r2 = self.session.get(gamerx_url, headers={"Referer": hubcloud_url}, timeout=20)
        soup2 = BeautifulSoup(r2.text, "html.parser")

        resolved = []

        # Find FSL Server
        for a in soup2.find_all("a", href=True):
            text = a.get_text(" ", strip=True)
            text_lower = text.lower()
            href = a["href"].strip()

            if "fsl server" in text_lower or a.get("id") == "fsl":
                resolved.append({
                    "server": "Download [FSL Server]",
                    "type": "Direct R2 / S3 Storage Link",
                    "url": href
                })
                break

        # Find Server : 10Gbps
        for a in soup2.find_all("a", href=True):
            text = a.get_text(" ", strip=True)
            text_lower = text.lower()
            href = a["href"].strip()

            if "server : 10gbps" in text_lower or ("server" in text_lower and "10gbps" in text_lower):
                # Follow pixel gateway to extract direct CDN link from dl.php?link=...
                direct_url = href
                try:
                    r_pixel = self.session.get(href, headers={"Referer": gamerx_url}, timeout=20)
                    parsed = urllib.parse.urlparse(r_pixel.url)
                    params = urllib.parse.parse_qs(parsed.query)
                    if "link" in params:
                        direct_url = params["link"][0]
                except Exception:
                    pass

                resolved.append({
                    "server": "Download [Server : 10Gbps]",
                    "type": "Direct Google Video CDN Link",
                    "url": direct_url,
                    "gateway_url": href if direct_url != href else None
                })
                break

        # Fallback: Find direct Cloudflare Worker or "Download File" link
        if not resolved:
            for a in soup2.find_all("a", href=True):
                text_low = a.get_text(" ", strip=True).lower()
                href = a["href"].strip()
                if ("download file" in text_low or "workers.dev" in href) and href.startswith("http"):
                    resolved.append({
                        "server": "Download [Cloudflare Worker]",
                        "type": "Direct Cloudflare R2 / Worker Stream",
                        "url": href
                    })
                    break

        return resolved

    def resolve_gdflix(self, gdflix_url: str) -> list[dict]:
        """
        Resolve GDFlix page with active mirror fallback:
        Prioritizes working mirrors (gdflix.dev, new3.gdflix.io) when given stale domains (e.g. new.gdflix.dad).
        Target priority:
        1. INSTANT DL [10GBPS] -> Google Video CDN Link
        2. CLOUD DOWNLOAD [R2] -> Direct Cloudflare R2 Stream / Download
        """
        parsed_orig = urllib.parse.urlparse(gdflix_url)
        path = parsed_orig.path

        # Candidate URLs to attempt
        candidates = []
        is_known_dead = any(dead in parsed_orig.netloc.lower() for dead in ["gdflix.dad", "new.gdflix"])

        # If known dead domain, prioritize active mirrors first
        if is_known_dead:
            for mirror in GDFLIX_WORKING_MIRRORS:
                candidates.append(f"{mirror.rstrip('/')}{path}")
            candidates.append(gdflix_url)
        else:
            candidates.append(gdflix_url)
            for mirror in GDFLIX_WORKING_MIRRORS:
                m_url = f"{mirror.rstrip('/')}{path}"
                if m_url not in candidates:
                    candidates.append(m_url)

        soup = None
        current_url = None

        for target in candidates:
            try:
                r = self.session.get(target, timeout=8)
                if r.status_code == 200 and len(r.text) > 500:
                    soup = BeautifulSoup(r.text, "html.parser")
                    current_url = r.url
                    break
            except Exception:
                continue

        if not soup:
            raise RuntimeError(f"All GDFlix mirrors failed for {gdflix_url}")

        resolved = []

        # 1. Find INSTANT DL [10GBPS]
        for a in soup.find_all("a", href=True):
            text = a.get_text(" ", strip=True)
            text_lower = text.lower()
            href = a["href"].strip()

            if "instant dl" in text_lower and "10gbps" in text_lower:
                direct_url = href
                try:
                    r_instant = self.session.get(href, headers={"Referer": current_url}, timeout=8)
                    parsed = urllib.parse.urlparse(r_instant.url)
                    params = urllib.parse.parse_qs(parsed.query)
                    if "url" in params:
                        direct_url = params["url"][0]
                    elif "link" in params:
                        direct_url = params["link"][0]
                except Exception:
                    pass

                resolved.append({
                    "server": "INSTANT DL [10GBPS]",
                    "type": "Direct Google Video CDN Link",
                    "url": direct_url,
                    "gateway_url": href if direct_url != href else None
                })
                break

        # 2. Find CLOUD DOWNLOAD [R2]
        for a in soup.find_all("a", href=True):
            text = a.get_text(" ", strip=True)
            text_lower = text.lower()
            href = a["href"].strip()

            if ("cloud download" in text_lower and "r2" in text_lower) or "fast cloud" in text_lower:
                if href.startswith("/"):
                    href = urllib.parse.urljoin(current_url, href)
                resolved.append({
                    "server": "CLOUD DOWNLOAD [R2]",
                    "type": "Direct Cloudflare R2 Stream / Download",
                    "url": href
                })
                break

        return resolved


def main():
    parser = argparse.ArgumentParser(
        description="Extract direct download URLs for Episode 1 (HubCloud FSL/10Gbps & GDFlix Instant/R2)."
    )
    parser.add_argument(
        "url",
        nargs="?",
        default=DEFAULT_DRAMA_URL,
        help=f"Drama page URL (default: {DEFAULT_DRAMA_URL})"
    )
    parser.add_argument(
        "-p", "--provider",
        choices=["all", "hubcloud", "gdflix"],
        default="all",
        help="Target provider: hubcloud, gdflix, or all (default: all)"
    )
    parser.add_argument(
        "-q", "--quality",
        default="1080p",
        help="Quality target (default: 1080p)"
    )
    parser.add_argument(
        "-r", "--raw",
        action="store_true",
        help="Output direct download URLs only (one per line)"
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output in JSON format"
    )
    parser.add_argument(
        "-o", "--output",
        help="Save output to file"
    )

    args = parser.parse_args()

    resolver = LinkResolver()

    if not args.raw and not args.json:
        print("=" * 70)
        print("EPISODE 1 DIRECT DOWNLOAD RESOLVER")
        print("=" * 70)
        print(f"[*] Drama URL : {args.url}")
        print(f"[*] Target    : Episode 1 ({args.quality} Single Episode, No Zip)")
        print(f"[*] Provider  : {args.provider.upper()}\n")

    # Step 1: Find single episode archive URL
    target_label, archive_url = resolver.get_target_archive_url(args.url, quality=args.quality)
    if not args.raw and not args.json:
        print(f"[+] Found Archive Link : [{target_label}]")
        print(f"[+] Archive URL        : {archive_url}\n")

    # Step 2: Extract Ep1 links from archive
    ep1_links = resolver.get_episode_1_links(archive_url)
    if not ep1_links:
        print("[!] Could not locate Episode 1 links on the archive page.", file=sys.stderr)
        sys.exit(1)

    results = {}

    # HubCloud resolution
    if args.provider in ["all", "hubcloud"]:
        if "hubcloud" in ep1_links:
            if not args.raw and not args.json:
                print(f"[*] Resolving HubCloud: {ep1_links['hubcloud']}...")
            results["hubcloud"] = {
                "landing_url": ep1_links["hubcloud"],
                "downloads": resolver.resolve_hubcloud(ep1_links["hubcloud"])
            }
        else:
            if not args.raw and not args.json:
                print("[!] No HubCloud link found for Episode 1.")

    # GDFlix resolution
    if args.provider in ["all", "gdflix"]:
        if "gdflix" in ep1_links:
            if not args.raw and not args.json:
                print(f"[*] Resolving GDFlix: {ep1_links['gdflix']}...")
            results["gdflix"] = {
                "landing_url": ep1_links["gdflix"],
                "downloads": resolver.resolve_gdflix(ep1_links["gdflix"])
            }
        else:
            if not args.raw and not args.json:
                print("[!] No GDFlix link found for Episode 1.")

    # Output formatting
    if args.json:
        json_str = json.dumps(results, indent=2, ensure_ascii=False)
        print(json_str)
        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(json_str)
        return

    # Extract flat list of direct download URLs
    direct_urls = []
    for prov_data in results.values():
        for item in prov_data.get("downloads", []):
            direct_urls.append(item["url"])

    if args.raw:
        urls_str = "\n".join(direct_urls)
        print(urls_str)
        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(urls_str + "\n")
        return

    # Default formatted output
    print("\n" + "=" * 70)
    print("EPISODE 1 DIRECT DOWNLOAD URLS")
    print("=" * 70)

    if "hubcloud" in results:
        print("\n🔹 HUBCLOUD (Priority: FSL Server & 10Gbps Server):")
        print(f"   Landing: {results['hubcloud']['landing_url']}")
        for d in results["hubcloud"]["downloads"]:
            print(f"\n   ✅ [{d['server']}] ({d['type']}):")
            print(f"      {d['url']}")

    if "gdflix" in results:
        print("\n" + "-" * 70)
        print("🔹 GDFLIX (Priority: INSTANT DL [10GBPS] & CLOUD DOWNLOAD [R2]):")
        print(f"   Landing: {results['gdflix']['landing_url']}")
        for d in results["gdflix"]["downloads"]:
            print(f"\n   ✅ [{d['server']}] ({d['type']}):")
            print(f"      {d['url']}")

    print("\n" + "=" * 70)
    print("DIRECT DOWNLOAD URLS (READY TO COPY / WGET / ARIA2):")
    print("=" * 70)
    for u in direct_urls:
        print(u)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write("\n".join(direct_urls) + "\n")
        print(f"\n[+] Saved {len(direct_urls)} URLs to: {args.output}")


if __name__ == "__main__":
    main()
